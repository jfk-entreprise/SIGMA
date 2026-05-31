import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:dio/dio.dart';

import 'package:sigma_app/core/security/secure_storage_service.dart';
import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/data/local/sync_dao.dart';
import 'package:sigma_app/data/repositories/sync_repository.dart';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

/// Cree un Dio dont chaque requete est resolue avec [statusCode].
Dio _mockDio(int statusCode) {
  final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        if (statusCode >= 200 && statusCode < 300) {
          handler.resolve(
            Response(requestOptions: options, statusCode: statusCode),
          );
        } else {
          handler.reject(
            DioException(
              requestOptions: options,
              response:
                  Response(requestOptions: options, statusCode: statusCode),
              type: DioExceptionType.badResponse,
            ),
          );
        }
      },
    ),
  );
  return dio;
}

/// Cree un Dio qui simule une perte de connexion (pas de reponse du serveur).
Dio _connectionErrorDio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) => handler.reject(
        DioException(
          requestOptions: options,
          type: DioExceptionType.connectionError,
        ),
      ),
    ),
  );
  return dio;
}

/// Cree un Dio qui simule une perte de cle Keystore Android.
/// L'intercepteur auth rejette la requete avec StorageKeyLostException
/// (identique au comportement de _AuthInterceptor dans api_client.dart).
Dio _keystoreErrorDio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) => handler.reject(
        DioException(
          requestOptions: options,
          type: DioExceptionType.unknown,
          error: const StorageKeyLostException(),
        ),
      ),
    ),
  );
  return dio;
}

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

void main() {
  late AppDatabase db;
  late SyncQueueDao dao;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    dao = SyncQueueDao(db);
  });

  tearDown(() => db.close());

  // ────────────────────────────────────────────────
  // SyncQueueDao — tests unitaires du DAO
  // ────────────────────────────────────────────────

  group("SyncQueueDao", () {
    test("addPendingAction insere avec statut PENDING et retryCount=0",
        () async {
      await dao.addPendingAction(
        id: 'uuid-a',
        operation: 'CREATE',
        entity: 'order',
        jsonPayload: '{"vehicle_number": "AB-001"}',
      );

      final rows = await dao.getPendingActionsFIFO();
      expect(rows.length, 1);
      expect(rows.first.id, 'uuid-a');
      expect(rows.first.status, 'PENDING');
      expect(rows.first.retryCount, 0);
    });

    test("getPendingActionsFIFO retourne les actions dans l'ordre chronologique",
        () async {
      final now = DateTime.now();
      for (var i = 0; i < 3; i++) {
        await db.into(db.syncQueue).insert(
              SyncQueueCompanion.insert(
                id: 'uuid-$i',
                operation: 'CREATE',
                entity: 'expense',
                payload: '{"seq": $i}',
                createdAt: Value(now.add(Duration(seconds: i))),
              ),
            );
      }

      final rows = await dao.getPendingActionsFIFO();
      expect(rows.map((r) => r.id).toList(), ['uuid-0', 'uuid-1', 'uuid-2']);
    });

    test("markAsSynced supprime l'action de la file", () async {
      await dao.addPendingAction(
        id: 'uuid-del',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 5000}',
      );
      await dao.markAsSynced('uuid-del');

      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });

    test("incrementRetryCount incremente de 0 a 1 puis a 2", () async {
      await dao.addPendingAction(
        id: 'uuid-retry',
        operation: 'CREATE',
        entity: 'credit',
        jsonPayload: '{"amount": 2000}',
      );

      await dao.incrementRetryCount('uuid-retry');
      final after1 = await dao.getPendingActionsFIFO();
      expect(after1.first.retryCount, 1);

      await dao.incrementRetryCount('uuid-retry');
      final after2 = await dao.getPendingActionsFIFO();
      expect(after2.first.retryCount, 2);
    });

    test("getPendingActionsFIFO ignore les lignes avec statut DONE", () async {
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'done-1',
              operation: 'CREATE',
              entity: 'order',
              payload: '{}',
              status: const Value('DONE'),
            ),
          );
      await dao.addPendingAction(
        id: 'pending-1',
        operation: 'CREATE',
        entity: 'order',
        jsonPayload: '{}',
      );

      final rows = await dao.getPendingActionsFIFO();
      expect(rows.length, 1);
      expect(rows.first.id, 'pending-1');
    });

    test("markAsFailed passe le statut a FAILED et exclut la ligne du FIFO",
        () async {
      await dao.addPendingAction(
        id: 'fail-1',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": -1}',
      );
      await dao.markAsFailed('fail-1');

      // La ligne disparait du FIFO
      expect(await dao.getPendingActionsFIFO(), isEmpty);

      // Mais reste dans la table pour audit
      final all = await (db.select(db.syncQueue)).get();
      expect(all.length, 1);
      expect(all.first.status, 'FAILED');
    });
  });

  // ────────────────────────────────────────────────
  // SyncCoordinator — comportement de base
  // ────────────────────────────────────────────────

  group("SyncCoordinator", () {
    test("sync supprime toutes les actions sur reponse 200", () async {
      for (var i = 0; i < 3; i++) {
        await dao.addPendingAction(
          id: 'ok-$i',
          operation: 'CREATE',
          entity: 'expense',
          jsonPayload: '{"amount": ${(i + 1) * 1000}}',
        );
      }

      await SyncCoordinator(dao: dao, client: _mockDio(200)).sync();

      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });

    test("sync traite 409 comme un succes (idempotence) et supprime l'action",
        () async {
      await dao.addPendingAction(
        id: 'dup-1',
        operation: 'CREATE',
        entity: 'order',
        jsonPayload: '{"vehicle_number": "XX-999"}',
      );

      await SyncCoordinator(dao: dao, client: _mockDio(409)).sync();

      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });

    test("sync s'arrete sur erreur transitoire et preserve l'ordre FIFO",
        () async {
      final now = DateTime.now();
      for (var i = 0; i < 2; i++) {
        await db.into(db.syncQueue).insert(
              SyncQueueCompanion.insert(
                id: 'trans-$i',
                operation: 'CREATE',
                entity: 'expense',
                payload: '{"amount": ${(i + 1) * 100}}',
                createdAt: Value(now.add(Duration(seconds: i))),
              ),
            );
      }

      await SyncCoordinator(dao: dao, client: _connectionErrorDio()).sync();

      final remaining = await dao.getPendingActionsFIFO();
      expect(remaining.length, 2);
      expect(remaining.first.id, 'trans-0');
      expect(remaining.first.retryCount, 1);
      expect(remaining.last.id, 'trans-1');
      expect(remaining.last.retryCount, 0);
    });

    test("sync passe a l'action suivante apres une erreur 422 (fatale)",
        () async {
      final now = DateTime.now();
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'bad-1',
              operation: 'CREATE',
              entity: 'expense',
              payload: '{"amount": -999}',
              createdAt: Value(now),
            ),
          );
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'good-1',
              operation: 'CREATE',
              entity: 'expense',
              payload: '{"amount": 500}',
              createdAt: Value(now.add(const Duration(seconds: 1))),
            ),
          );

      await SyncCoordinator(dao: dao, client: _mockDio(422)).sync();

      final remaining = await dao.getPendingActionsFIFO();
      expect(remaining.length, 2);
      expect(remaining.first.retryCount, 1);
      expect(remaining.last.retryCount, 1);
    });

    test("sync est sans effet sur une file vide", () async {
      await expectLater(
        SyncCoordinator(dao: dao, client: _mockDio(200)).sync(),
        completes,
      );
    });

    test("sync resout correctement l'endpoint /pay via le champ order_id",
        () async {
      String? capturedUrl;
      final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            capturedUrl = options.path;
            handler.resolve(
              Response(requestOptions: options, statusCode: 200),
            );
          },
        ),
      );

      await dao.addPendingAction(
        id: 'pay-1',
        operation: 'CREATE',
        entity: 'payment',
        jsonPayload: '{"order_id": "order-uuid-xyz", "amount": 3000}',
      );

      await SyncCoordinator(dao: dao, client: dio).sync();

      expect(capturedUrl, '/api/v1/orders/order-uuid-xyz/pay');
      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });
  });

  // ────────────────────────────────────────────────
  // Correctifs QA — sécurité et robustesse
  // ────────────────────────────────────────────────

  group("Correctifs QA", () {
    // ── Correctif #2 : 401 Unauthorized ────────────────────────────

    test("sync s'arrete immediatement sur 401 et appelle onAuthRequired",
        () async {
      await dao.addPendingAction(
        id: 'auth-1',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 100}',
      );
      await dao.addPendingAction(
        id: 'auth-2',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 200}',
      );

      var authCallbackCalled = false;
      await SyncCoordinator(
        dao: dao,
        client: _mockDio(401),
        onAuthRequired: () => authCallbackCalled = true,
      ).sync();

      expect(authCallbackCalled, isTrue);

      // Les deux actions restent PENDING — retryCount non incremente sur 401
      final remaining = await dao.getPendingActionsFIFO();
      expect(remaining.length, 2);
      expect(remaining.first.retryCount, 0);
      expect(remaining.last.retryCount, 0);
    });

    test("sync ne tente pas la 2eme action apres un 401 (pas de drain batterie)",
        () async {
      var requestCount = 0;
      final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
      dio.interceptors.add(InterceptorsWrapper(
        onRequest: (options, handler) {
          requestCount++;
          handler.reject(DioException(
            requestOptions: options,
            response: Response(requestOptions: options, statusCode: 401),
            type: DioExceptionType.badResponse,
          ));
        },
      ));

      for (var i = 0; i < 5; i++) {
        await dao.addPendingAction(
          id: 'drain-$i',
          operation: 'CREATE',
          entity: 'expense',
          jsonPayload: '{"amount": $i}',
        );
      }

      await SyncCoordinator(dao: dao, client: dio).sync();

      // Une seule requete HTTP envoyee, pas 5
      expect(requestCount, 1);
    });

    // ── Correctif #2 : Keystore Android perdu ──────────────────────

    test("sync detecte StorageKeyLostException et appelle onAuthRequired",
        () async {
      await dao.addPendingAction(
        id: 'ks-1',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 500}',
      );
      await dao.addPendingAction(
        id: 'ks-2',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 1000}',
      );

      var authCalled = false;
      await SyncCoordinator(
        dao: dao,
        client: _keystoreErrorDio(),
        onAuthRequired: () => authCalled = true,
      ).sync();

      expect(authCalled, isTrue);

      // Les actions restent PENDING — pas de penalite retryCount
      final remaining = await dao.getPendingActionsFIFO();
      expect(remaining.length, 2);
      expect(remaining.first.retryCount, 0);
      expect(remaining.last.retryCount, 0);
    });

    // ── Correctif #3 : Poison Pill / seuil max retry ───────────────

    test("action Poison Pill passe en FAILED apres _kMaxRetryCount tentatives",
        () async {
      final now = DateTime.now();

      // Action avec retryCount deja au seuil (5)
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'poison-1',
              operation: 'CREATE',
              entity: 'expense',
              payload: '{"amount": -1}',
              retryCount: const Value(5),
              createdAt: Value(now),
            ),
          );

      // Action valide independante qui suit
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'valid-1',
              operation: 'CREATE',
              entity: 'expense',
              payload: '{"amount": 500}',
              createdAt: Value(now.add(const Duration(seconds: 1))),
            ),
          );

      // 422 pour toutes les requetes — poison pill ne guerira pas
      await SyncCoordinator(dao: dao, client: _mockDio(422)).sync();

      final allRows = await (db.select(db.syncQueue)).get();

      // La Poison Pill doit etre archivee en FAILED
      final poison = allRows.firstWhere((r) => r.id == 'poison-1');
      expect(poison.status, 'FAILED');

      // L'action valide a ete tentee (422) et son retryCount est incremente (0→1)
      final valid = allRows.firstWhere((r) => r.id == 'valid-1');
      expect(valid.status, 'PENDING');
      expect(valid.retryCount, 1);
    });

    test("action sous le seuil incremente retryCount sans passer en FAILED",
        () async {
      await dao.addPendingAction(
        id: 'below-1',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": -1}',
      );

      // 4 cycles de 422 (retryCount passe de 0 a 4, seuil = 5)
      for (var cycle = 0; cycle < 4; cycle++) {
        await SyncCoordinator(dao: dao, client: _mockDio(422)).sync();
      }

      final rows = await dao.getPendingActionsFIFO();
      expect(rows.length, 1); // toujours PENDING, pas FAILED
      expect(rows.first.retryCount, 4);
      expect(rows.first.status, 'PENDING');
    });

    test("action exactement au seuil (retryCount=5) est archivee FAILED au cycle suivant",
        () async {
      // Inserer avec retryCount = 4 (juste en dessous)
      await db.into(db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: 'threshold-1',
              operation: 'CREATE',
              entity: 'expense',
              payload: '{"amount": -1}',
              retryCount: const Value(4),
            ),
          );

      // Cycle 1 : retryCount 4 < 5 → on incremente → retryCount = 5
      await SyncCoordinator(dao: dao, client: _mockDio(422)).sync();
      final afterCycle1 = await dao.getPendingActionsFIFO();
      expect(afterCycle1.first.retryCount, 5); // encore PENDING

      // Cycle 2 : retryCount 5 >= 5 → markAsFailed
      await SyncCoordinator(dao: dao, client: _mockDio(422)).sync();
      expect(await dao.getPendingActionsFIFO(), isEmpty); // sorti de la file

      final allRows = await (db.select(db.syncQueue)).get();
      expect(allRows.first.status, 'FAILED');
    });

    // ── Correctif #4 : Verrou de concurrence ───────────────────────

    test("verrou de reentrancy — appels simultanes n'envoient qu'une seule serie de requetes",
        () async {
      for (var i = 0; i < 3; i++) {
        await dao.addPendingAction(
          id: 'conc-$i',
          operation: 'CREATE',
          entity: 'expense',
          jsonPayload: '{"amount": ${(i + 1) * 100}}',
        );
      }

      var requestCount = 0;
      final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000'));
      dio.interceptors.add(InterceptorsWrapper(
        onRequest: (options, handler) {
          requestCount++;
          handler.resolve(Response(requestOptions: options, statusCode: 200));
        },
      ));

      final coordinator = SyncCoordinator(dao: dao, client: dio);

      // Lancer deux sync() en parallele — le second doit etre ignore
      await Future.wait([coordinator.sync(), coordinator.sync()]);

      // Exactement 3 requetes (une par action), pas 6
      expect(requestCount, 3);
      // File entierement drainee
      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });

    test("second sync() apres la fin du premier traite normalement les nouvelles actions",
        () async {
      await dao.addPendingAction(
        id: 'seq-1',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 100}',
      );

      final coordinator = SyncCoordinator(
        dao: dao,
        client: _mockDio(200),
      );

      // Premier sync : draine seq-1
      await coordinator.sync();
      expect(await dao.getPendingActionsFIFO(), isEmpty);

      // Nouvelle action ajoutee apres le premier sync
      await dao.addPendingAction(
        id: 'seq-2',
        operation: 'CREATE',
        entity: 'expense',
        jsonPayload: '{"amount": 200}',
      );

      // Deuxieme sync : _isSyncing a ete remis a false → traite seq-2
      await coordinator.sync();
      expect(await dao.getPendingActionsFIFO(), isEmpty);
    });
  });
}
