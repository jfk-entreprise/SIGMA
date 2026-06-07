part of 'auth_bloc.dart';

sealed class AuthState {
  const AuthState();
}

final class AuthLoading extends AuthState {
  const AuthLoading();
}

final class AuthNoData extends AuthState {
  const AuthNoData();
}

/// L'utilisateur doit créer ou confirmer son code PIN.
final class AuthPinCreation extends AuthState {
  final List<String> digits;
  final bool confirmMode;
  final String firstPin;
  final String? error;

  const AuthPinCreation({
    this.digits = const [],
    this.confirmMode = false,
    this.firstPin = '',
    this.error,
  });

  AuthPinCreation copyWith({
    List<String>? digits,
    bool? confirmMode,
    String? firstPin,
    String? error,
  }) =>
      AuthPinCreation(
        digits: digits ?? this.digits,
        confirmMode: confirmMode ?? this.confirmMode,
        firstPin: firstPin ?? this.firstPin,
        error: error,
      );
}

/// Le PIN existe déjà — déverrouillage requis.
final class AuthUnlock extends AuthState {
  final List<String> digits;
  final String? error;

  const AuthUnlock({this.digits = const [], this.error});

  AuthUnlock copyWith({List<String>? digits, String? error}) =>
      AuthUnlock(digits: digits ?? this.digits, error: error);
}

/// Authentification réussie.
final class AuthAuthenticated extends AuthState {
  final LocalBusinessesData business;
  final LocalUser? user; // LocalUser = nom généré par Drift pour LocalUsers table

  const AuthAuthenticated({required this.business, this.user});
}

/// Accès temporairement verrouillé après trop de tentatives.
final class AuthLockedOut extends AuthState {
  final int remainingSeconds;
  const AuthLockedOut({required this.remainingSeconds});
}
