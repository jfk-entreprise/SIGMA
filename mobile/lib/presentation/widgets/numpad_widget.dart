import 'package:flutter/material.dart';

/// Numpad visuel 3×4 pour la saisie du code PIN.
///
/// Layout :
///   [1] [2] [3]
///   [4] [5] [6]
///   [7] [8] [9]
///       [0] [⌫]
///
/// Les boutons chiffres sont de grands cercles blancs ombrés.
/// La touche effacement utilise un fond gris discret.
class NumpadWidget extends StatelessWidget {
  final void Function(String digit) onDigit;
  final VoidCallback onBackspace;
  final bool backspaceEnabled;

  const NumpadWidget({
    super.key,
    required this.onDigit,
    required this.onBackspace,
    this.backspaceEnabled = true,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _row(['1', '2', '3']),
        const SizedBox(height: 16),
        _row(['4', '5', '6']),
        const SizedBox(height: 16),
        _row(['7', '8', '9']),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(width: 80), // espace vide à gauche
            const SizedBox(width: 16),
            _digitButton('0'),
            const SizedBox(width: 16),
            _backspaceButton(),
          ],
        ),
      ],
    );
  }

  Widget _row(List<String> digits) => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: digits
            .expand((d) => [_digitButton(d), const SizedBox(width: 16)])
            .toList()
          ..removeLast(),
      );

  Widget _digitButton(String digit) => _PinButton(
        onTap: () => onDigit(digit),
        child: Text(
          digit,
          style: const TextStyle(
            fontSize: 26,
            fontWeight: FontWeight.w500,
            color: Color(0xFF1A1A2E),
          ),
        ),
      );

  Widget _backspaceButton() => _PinButton(
        onTap: backspaceEnabled ? onBackspace : null,
        color: const Color(0xFFECEFF1),
        child: Icon(
          Icons.backspace_outlined,
          size: 24,
          color: backspaceEnabled
              ? const Color(0xFF546E7A)
              : const Color(0xFFB0BEC5),
        ),
      );
}

class _PinButton extends StatelessWidget {
  final VoidCallback? onTap;
  final Widget child;
  final Color color;

  const _PinButton({
    required this.onTap,
    required this.child,
    this.color = Colors.white,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color,
      shape: const CircleBorder(),
      elevation: onTap != null ? 3 : 0,
      shadowColor: Colors.black26,
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: SizedBox(
          width: 76,
          height: 76,
          child: Center(child: child),
        ),
      ),
    );
  }
}
