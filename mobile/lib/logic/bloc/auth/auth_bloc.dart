import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/core/security/secure_storage_service.dart';
import 'package:sigma_app/data/local/database.dart';

part 'auth_event.dart';
part 'auth_state.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  final AppDatabase _db;

  static const int _kMaxAttempts = 5;
  static const int _kLockoutSeconds = 30;
  static const int kSessionTimeoutSeconds = 300; // 5 min d'inactivité

  int _failedAttempts = 0;
  Timer? _lockoutTimer;
  int _lockoutRemaining = 0;

  AuthBloc({required AppDatabase db})
      : _db = db,
        super(const AuthLoading()) {
    on<AuthStarted>(_onStarted);
    on<AuthDigitPressed>(_onDigitPressed);
    on<AuthBackspacePressed>(_onBackspacePressed);
    on<AuthLockRequested>(_onLockRequested);
    on<_AuthLockoutTick>(_onLockoutTick);
  }

  @override
  Future<void> close() {
    _lockoutTimer?.cancel();
    return super.close();
  }

  // ──────────────────────────────────────────────────────────────────
  // Handlers
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onStarted(
    AuthStarted event,
    Emitter<AuthState> emit,
  ) async {
    try {
      final has = await SecureStorageService.hasPinHash();
      emit(has ? const AuthUnlock() : const AuthPinCreation());
    } on StorageKeyLostException {
      // Clé Keystore perdue → repartir de zéro proprement
      emit(const AuthPinCreation());
    } catch (_) {
      emit(const AuthPinCreation());
    }
  }

  Future<void> _onDigitPressed(
    AuthDigitPressed event,
    Emitter<AuthState> emit,
  ) async {
    final s = state;

    if (s is AuthPinCreation) {
      if (s.digits.length >= 4) return;
      final next = [...s.digits, event.digit];

      if (next.length < 4) {
        emit(s.copyWith(digits: next));
        return;
      }

      // 4 chiffres saisis
      final pin = next.join();

      if (!s.confirmMode) {
        // Passage à la confirmation
        emit(AuthPinCreation(confirmMode: true, firstPin: pin));
      } else {
        // Vérification confirmation
        if (pin == s.firstPin) {
          await SecureStorageService.savePinHash(_hash(pin));
          await _loadAuthenticated(emit);
        } else {
          emit(const AuthPinCreation(error: 'PIN différent. Recommencez.'));
        }
      }
    } else if (s is AuthUnlock) {
      if (s.digits.length >= 4) return;
      final next = [...s.digits, event.digit];

      if (next.length < 4) {
        emit(s.copyWith(digits: next));
        return;
      }

      // Vérification du PIN
      final pin = next.join();
      final stored = await SecureStorageService.getPinHash();

      if (stored != null && stored == _hash(pin)) {
        _failedAttempts = 0;
        await _loadAuthenticated(emit);
      } else {
        _failedAttempts++;
        if (_failedAttempts >= _kMaxAttempts) {
          _failedAttempts = 0;
          _lockoutRemaining = _kLockoutSeconds;
          _lockoutTimer?.cancel();
          _lockoutTimer = Timer.periodic(const Duration(seconds: 1), (_) {
            add(const _AuthLockoutTick());
          });
          emit(AuthLockedOut(remainingSeconds: _lockoutRemaining));
        } else {
          final remaining = _kMaxAttempts - _failedAttempts;
          emit(AuthUnlock(
            error: 'PIN incorrect · $remaining essai(s) restant(s)',
          ));
        }
      }
    }
  }

  void _onBackspacePressed(
    AuthBackspacePressed event,
    Emitter<AuthState> emit,
  ) {
    final s = state;
    if (s is AuthPinCreation && s.digits.isNotEmpty) {
      emit(s.copyWith(digits: s.digits.sublist(0, s.digits.length - 1)));
    } else if (s is AuthUnlock && s.digits.isNotEmpty) {
      emit(s.copyWith(digits: s.digits.sublist(0, s.digits.length - 1)));
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Helpers
  // ──────────────────────────────────────────────────────────────────

  Future<void> _loadAuthenticated(Emitter<AuthState> emit) async {
    emit(const AuthLoading());
    try {
      final businesses =
          await (_db.select(_db.localBusinesses)..limit(1)).get();
      if (businesses.isEmpty) {
        emit(const AuthNoData());
        return;
      }
      final business = businesses.first;
      final user = await (_db.select(_db.localUsers)
            ..where((t) => t.id.equals(business.ownerId))
            ..limit(1))
          .getSingleOrNull();
      emit(AuthAuthenticated(business: business, user: user));
    } catch (_) {
      emit(const AuthUnlock(error: 'Erreur de chargement.'));
    }
  }

  void _onLockoutTick(
    _AuthLockoutTick event,
    Emitter<AuthState> emit,
  ) {
    _lockoutRemaining--;
    if (_lockoutRemaining <= 0) {
      _lockoutTimer?.cancel();
      _lockoutTimer = null;
      emit(const AuthUnlock());
    } else {
      emit(AuthLockedOut(remainingSeconds: _lockoutRemaining));
    }
  }

  void _onLockRequested(
    AuthLockRequested event,
    Emitter<AuthState> emit,
  ) {
    _lockoutTimer?.cancel();
    _lockoutTimer = null;
    _failedAttempts = 0;
    emit(const AuthUnlock());
  }

  String _hash(String pin) =>
      sha256.convert(utf8.encode(pin)).toString();
}
