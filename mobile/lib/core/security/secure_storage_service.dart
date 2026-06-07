import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Levée quand le Keystore Android perd ou corrompt sa clé de chiffrement.
///
/// Cas déclencheurs : mise à jour d'OS majeure, réinitialisation partielle,
/// changement de PIN sans migration de clé (certains MediaTek / Unisoc).
/// Les appelants doivent effacer la session locale et forcer une reconnexion.
class StorageKeyLostException implements Exception {
  const StorageKeyLostException();
  @override
  String toString() =>
      'StorageKeyLostException: cle Keystore perdue — reconnexion obligatoire.';
}

/// Singleton autour de [FlutterSecureStorage] avec résilience Keystore.
///
/// Toutes les lectures / écritures transitent par [_safeRead] / [_safeWrite]
/// qui capturent les [PlatformException] matérielles et lèvent
/// [StorageKeyLostException] à la place d'un crash fatal.
class SecureStorageService {
  SecureStorageService._();

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  static const _kAccessToken = 'sigma_access_token';
  static const _kRefreshToken = 'sigma_refresh_token';
  static const _kPinHash = 'sigma_pin_hash';

  // ──────────────────────────────────────────────────────────────────
  // API publique
  // ──────────────────────────────────────────────────────────────────

  static Future<String?> getAccessToken() => _safeRead(_kAccessToken);
  static Future<String?> getRefreshToken() => _safeRead(_kRefreshToken);

  /// Persiste les deux jetons après login ou refresh réussi.
  static Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await _safeWrite(_kAccessToken, accessToken);
    await _safeWrite(_kRefreshToken, refreshToken);
  }

  // ── PIN ──────────────────────────────────────────────────────────

  static Future<bool> hasPinHash() async {
    try {
      final h = await _safeRead(_kPinHash);
      return h != null && h.isNotEmpty;
    } on StorageKeyLostException {
      return false;
    }
  }

  static Future<String?> getPinHash() => _safeRead(_kPinHash);

  static Future<void> savePinHash(String hash) =>
      _safeWrite(_kPinHash, hash);

  // ──────────────────────────────────────────────────────────────────

  /// Efface tous les secrets (déconnexion, changement de compte).
  static Future<void> clearAll() async {
    try {
      await _storage.deleteAll();
    } on PlatformException {
      // Keystore complètement irrécupérable — ne pas propager.
      // L'app redémarre en état vierge au prochain lancement.
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Wrappers défensifs (usage interne uniquement)
  // ──────────────────────────────────────────────────────────────────

  static Future<String?> _safeRead(String key) async {
    try {
      return await _storage.read(key: key);
    } on PlatformException {
      // Clé AES du Keystore perdue (ex: AEADBadTagException sur Android 12+).
      // On purge le stockage pour éviter un état incohérent permanent,
      // puis on délègue la gestion de la déconnexion à l'appelant.
      await clearAll();
      throw const StorageKeyLostException();
    }
  }

  static Future<void> _safeWrite(String key, String value) async {
    try {
      await _storage.write(key: key, value: value);
    } on PlatformException {
      await clearAll();
      throw const StorageKeyLostException();
    }
  }
}
