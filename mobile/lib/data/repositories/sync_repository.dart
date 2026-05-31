import 'dart:convert';
import 'package:dio/dio.dart';
import '../local/sync_dao.dart';
import '../local/database.dart';
import 'package:sigma_app/core/security/secure_storage_service.dart';

// ──────────────────────────────────────────────────────────────────────────────
// Constantes
// ──────────────────────────────────────────────────────────────────────────────

/// Nombre maximum de tentatives avant qu'une action soit archivée comme FAILED.
/// Au-delà de ce seuil, l'action est irrémédiablement invalide (mauvais payload,
/// entité inconnue…) et ne doit plus bloquer les actions indépendantes qui la suivent.
const int _kMaxRetryCount = 5;

// ──────────────────────────────────────────────────────────────────────────────
// Types de résultat internes
// ──────────────────────────────────────────────────────────────────────────────

sealed class _Outcome {}

/// L'API a répondu 2xx, ou 409 (entité déjà existante — idempotence garantie).
class _Success extends _Outcome {}

/// Erreur transitoire : connexion perdue, timeout, 5xx.
/// Le cycle s'arrête immédiatement pour préserver l'ordre FIFO.
class _Transient extends _Outcome {}

/// Erreur permanente : payload invalide (422), entité inconnue, etc.
/// On continue vers l'action suivante (évite la "Poison Pill").
/// Si [retryCount] atteint [_kMaxRetryCount], l'action est archivée FAILED.
class _Fatal extends _Outcome {}

/// Le serveur a retourné 401, ou le Keystore Android a perdu sa clé.
/// Le cycle s'arrête immédiatement et [onAuthRequired] est appelé pour
/// notifier la couche UI qu'une reconnexion est nécessaire.
class _AuthRequired extends _Outcome {}

// ──────────────────────────────────────────────────────────────────────────────
// SyncCoordinator
// ──────────────────────────────────────────────────────────────────────────────

/// Moteur de synchronisation offline → serveur.
///
/// Invariants :
/// 1. **FIFO strict sur les erreurs transitoires** : si une action échoue
///    par manque de connectivité, toutes les actions suivantes attendent.
/// 2. **Continuité sur les erreurs permanentes** : un payload invalide (4xx)
///    ne bloque pas les actions indépendantes qui suivent.
/// 3. **Stop immédiat sur 401 / Keystore** : pas de requêtes inutiles,
///    notification de reconnexion via [onAuthRequired].
/// 4. **Verrou de réentrance** : [_isSyncing] empêche les appels concurrents
///    de doubler les requêtes HTTP sur les réseaux instables.
class SyncCoordinator {
  final SyncQueueDao _dao;
  final Dio _client;

  /// Appelé si le serveur répond 401 ou si le Keystore Android est corrompu.
  /// Le BLoC/Cubit parent doit déclencher le flux de reconnexion.
  final void Function()? onAuthRequired;

  bool _isSyncing = false;

  SyncCoordinator({
    required SyncQueueDao dao,
    required Dio client,
    this.onAuthRequired,
  })  : _dao = dao,
        _client = client;

  /// Draine la file PENDING dans l'ordre chronologique.
  ///
  /// Retourne normalement quand la file est vide ou qu'une pause est requise.
  /// Ne lève jamais d'exception — toutes les erreurs sont absorbées et
  /// consignées dans [retryCount] / statut [FAILED].
  Future<void> sync() async {
    // Verrou de réentrance : ignorer les appels concurrents pour éviter
    // les requêtes HTTP doublons sur les réseaux instables.
    if (_isSyncing) return;
    _isSyncing = true;

    try {
      final actions = await _dao.getPendingActionsFIFO();

      for (final action in actions) {
        final outcome = await _dispatch(action);

        switch (outcome) {
          case _Success():
            await _dao.markAsSynced(action.id);

          case _Transient():
            // Stopper le cycle — une action ultérieure ne doit PAS précéder
            // celle-ci pour maintenir la cohérence FIFO.
            await _dao.incrementRetryCount(action.id);
            return;

          case _AuthRequired():
            // Ne pas incrémenter retryCount : ce n'est pas la faute de l'action.
            // Stopper le cycle et déléguer la reconnexion à la couche UI.
            onAuthRequired?.call();
            return;

          case _Fatal():
            if (action.retryCount >= _kMaxRetryCount) {
              // L'action ne guérira pas — on l'archive pour libérer la file.
              await _dao.markAsFailed(action.id);
            } else {
              await _dao.incrementRetryCount(action.id);
            }
        }
      }
    } finally {
      _isSyncing = false;
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Interne
  // ──────────────────────────────────────────────────────────────────────────

  Future<_Outcome> _dispatch(SyncQueueData action) async {
    final endpoint =
        _resolveEndpoint(action.entity, action.operation, action.payload);
    if (endpoint == null) return _Fatal();

    try {
      await _client.post<dynamic>(
        endpoint,
        data: action.payload,
        options: Options(
          headers: {
            // UUID client = Idempotency-Key : une double livraison ne crée
            // jamais de doublon si le serveur gère correctement l'unicité UUID.
            'Idempotency-Key': action.id,
          },
        ),
      );
      return _Success();
    } on DioException catch (e) {
      // Clé Keystore perdue (intercepteur auth a positionné error=StorageKeyLostException)
      if (e.error is StorageKeyLostException) return _AuthRequired();

      final status = e.response?.statusCode;

      if (status != null) {
        // 401 Unauthorized : token expiré ou révoqué → reconnexion obligatoire.
        // Vérifié AVANT le bloc 4xx générique pour stopper le cycle immédiatement
        // (évite N requêtes inutiles si toute la file est bloquée par le même 401).
        if (status == 401) return _AuthRequired();

        // 409 Conflict : entité déjà créée → idempotent, considéré comme succès.
        if (status == 409) return _Success();

        // Autre 4xx : payload invalide, accès refusé, entité inconnue…
        if (status >= 400 && status < 500) return _Fatal();
      }

      // Pas de réponse (timeout, perte réseau) ou 5xx → erreur transitoire.
      return _Transient();
    }
  }

  /// Traduit (entity, operation) en URL d'endpoint SIGMA.
  /// Retourne [null] si la combinaison est inconnue → mappé sur [_Fatal].
  String? _resolveEndpoint(
    String entity,
    String operation,
    String payload,
  ) {
    switch (entity) {
      case 'order':
        return '/api/v1/orders/';

      case 'payment':
        final orderId = _jsonField(payload, 'order_id');
        return orderId != null ? '/api/v1/orders/$orderId/pay' : null;

      case 'expense':
        return '/api/v1/expenses/';

      case 'credit':
        return '/api/v1/credits/';

      default:
        return null;
    }
  }

  String? _jsonField(String json, String key) {
    try {
      final map = jsonDecode(json) as Map<String, dynamic>;
      return map[key]?.toString();
    } catch (_) {
      return null;
    }
  }
}
