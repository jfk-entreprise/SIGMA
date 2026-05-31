import 'package:dio/dio.dart';
import '../security/secure_storage_service.dart';

// Android émulateur → hôte local du PC de développement.
// En production, remplacer par l'URL HTTPS du serveur SIGMA.
const String _kBaseUrl = 'http://10.0.2.2:8000';

/// Instance Dio globale préconfigurée.
/// Utiliser [apiClient] partout plutôt que de créer des instances isolées.
final Dio apiClient = _buildDio();

Dio _buildDio() {
  final dio = Dio(
    BaseOptions(
      baseUrl: _kBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
      headers: {'Content-Type': 'application/json'},
    ),
  );
  dio.interceptors.add(_AuthInterceptor());
  return dio;
}

/// Intercepteur de sécurité : attache le Bearer token à chaque requête.
///
/// Gère deux cas d'échec :
/// - Clé Keystore perdue ([StorageKeyLostException]) → requête rejetée
///   proprement via [DioException] avec `error: StorageKeyLostException`.
///   Le [SyncCoordinator] l'intercepte et déclenche la reconnexion.
/// - Token absent (session non initialisée) → requête envoyée sans
///   Authorization ; les endpoints protégés répondront 401.
class _AuthInterceptor extends Interceptor {
  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    try {
      final token = await SecureStorageService.getAccessToken();
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
      handler.next(options);
    } on StorageKeyLostException catch (e) {
      // Rejeter la requête avec l'exception typée pour que le SyncCoordinator
      // et les couches supérieures puissent déclencher le flux de reconnexion.
      handler.reject(
        DioException(
          requestOptions: options,
          type: DioExceptionType.unknown,
          error: e,
        ),
      );
    }
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    // Propager telle quelle — la gestion du 401 / refresh token
    // sera implémentée en Étape 3.3 (AuthRepository).
    handler.next(err);
  }
}
