import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/logic/bloc/auth/auth_bloc.dart';
import 'package:sigma_app/presentation/widgets/numpad_widget.dart';

/// Écran de saisie du code PIN — gère à la fois la création initiale
/// (deux saisies pour confirmation) et le déverrouillage quotidien.
class PinScreen extends StatelessWidget {
  const PinScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6FA),
      body: SafeArea(
        child: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            final digits = switch (state) {
              AuthPinCreation(:final digits) => digits,
              AuthUnlock(:final digits) => digits,
              _ => const <String>[],
            };

            final subtitle = switch (state) {
              AuthPinCreation(:final confirmMode) => confirmMode
                  ? 'Confirmez votre code PIN'
                  : 'Créez votre code PIN à 4 chiffres',
              AuthUnlock() => 'Déverrouillez votre écran',
              AuthLockedOut(:final remainingSeconds) =>
                'Accès bloqué · Réessayez dans ${remainingSeconds}s',
              _ => 'Chargement…',
            };

            final error = switch (state) {
              AuthPinCreation(:final error) => error,
              AuthUnlock(:final error) => error,
              _ => null,
            };

            final isReady = state is AuthPinCreation || state is AuthUnlock;
            final isLocked = state is AuthLockedOut;

            return Column(
              children: [
                const Spacer(flex: 2),

                // ── Logo & titre ────────────────────────────────────
                const Icon(Icons.lock_outline_rounded,
                    size: 52, color: Color(0xFF1565C0)),
                const SizedBox(height: 12),
                const Text(
                  'SIGMA',
                  style: TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 4,
                    color: Color(0xFF1A1A2E),
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 15,
                    color: Color(0xFF607D8B),
                  ),
                ),

                const Spacer(),

                // ── Indicateurs de chiffres ─────────────────────────
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List.generate(4, (i) {
                    final filled = i < digits.length;
                    return Container(
                      margin: const EdgeInsets.symmetric(horizontal: 10),
                      width: 16,
                      height: 16,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: filled
                            ? const Color(0xFF1565C0)
                            : Colors.transparent,
                        border: Border.all(
                          color: filled
                              ? const Color(0xFF1565C0)
                              : const Color(0xFF90A4AE),
                          width: 2,
                        ),
                      ),
                    );
                  }),
                ),

                // ── Message d'erreur ────────────────────────────────
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 250),
                  child: error != null
                      ? Padding(
                          key: ValueKey(error),
                          padding: const EdgeInsets.only(top: 14),
                          child: Text(
                            error,
                            style: const TextStyle(
                              color: Color(0xFFD32F2F),
                              fontSize: 13,
                            ),
                          ),
                        )
                      : const SizedBox(height: 28),
                ),

                const Spacer(),

                // ── Numpad ──────────────────────────────────────────
                if (isReady && !isLocked)
                  NumpadWidget(
                    onDigit: (d) =>
                        context.read<AuthBloc>().add(AuthDigitPressed(d)),
                    onBackspace: () =>
                        context.read<AuthBloc>().add(const AuthBackspacePressed()),
                    backspaceEnabled: digits.isNotEmpty,
                  ),

                const Spacer(flex: 2),
              ],
            );
          },
        ),
      ),
    );
  }
}
