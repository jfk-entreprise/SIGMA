import 'package:drift/drift.dart';
import 'database.dart';

/// DAO pour la table [SyncQueue] — file d'attente offline-first.
///
/// Toutes les opérations sont asynchrones et s'exécutent sur le thread
/// d'arrière-plan géré par Drift (pas de blocage du thread UI).
class SyncQueueDao {
  final AppDatabase _db;

  SyncQueueDao(this._db);

  // ──────────────────────────────────────────────────────────────────
  // ÉCRITURE
  // ──────────────────────────────────────────────────────────────────

  /// Enfile une nouvelle action avec le statut PENDING.
  ///
  /// [id] : UUID v4 généré côté client — sert également d'Idempotency-Key HTTP.
  /// [operation] : CREATE | UPDATE | DELETE.
  /// [entity] : order | payment | expense | credit | …
  /// [jsonPayload] : corps de la requête API sérialisé en JSON.
  Future<void> addPendingAction({
    required String id,
    required String operation,
    required String entity,
    required String jsonPayload,
  }) =>
      _db.into(_db.syncQueue).insert(
            SyncQueueCompanion.insert(
              id: id,
              operation: operation,
              entity: entity,
              payload: jsonPayload,
              // status et retryCount utilisent leurs valeurs DEFAULT Drift
            ),
          );

  // ──────────────────────────────────────────────────────────────────
  // LECTURE
  // ──────────────────────────────────────────────────────────────────

  /// Retourne toutes les actions PENDING dans l'ordre chronologique (FIFO).
  ///
  /// L'ordre est garanti par [createdAt ASC] — critique pour ne jamais
  /// envoyer une action qui dépend d'une action antérieure non encore synchronisée.
  Future<List<SyncQueueData>> getPendingActionsFIFO() =>
      (_db.select(_db.syncQueue)
            ..where((t) => t.status.equals('PENDING'))
            ..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
          .get();

  // ──────────────────────────────────────────────────────────────────
  // MISE À JOUR / SUPPRESSION
  // ──────────────────────────────────────────────────────────────────

  /// Supprime l'action de la file après synchronisation réussie (2xx ou 409).
  Future<void> markAsSynced(String id) =>
      (_db.delete(_db.syncQueue)..where((t) => t.id.equals(id))).go();

  /// Archive une action comme définitivement échouée.
  ///
  /// Appelée quand [retryCount] atteint le seuil [_kMaxRetryCount].
  /// L'action reste dans la table pour audit/debug mais est exclue de
  /// [getPendingActionsFIFO] (filtre sur statut PENDING uniquement).
  Future<void> markAsFailed(String id) =>
      (_db.update(_db.syncQueue)..where((t) => t.id.equals(id))).write(
        const SyncQueueCompanion(status: Value('FAILED')),
      );

  /// Incrémente [retryCount] après une erreur transitoire (timeout, perte réseau).
  ///
  /// Utilise une UPDATE atomique SQL pour éviter un aller-retour SELECT + UPDATE
  /// qui introduirait une race condition si deux coroutines accèdent à la même ligne.
  Future<void> incrementRetryCount(String id) => _db.customUpdate(
        'UPDATE sync_queue SET retry_count = retry_count + 1 WHERE id = ?',
        variables: [Variable.withString(id)],
        updates: {_db.syncQueue},
      );
}
