import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/core/utils/formatters.dart';
import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/logic/bloc/orders/order_bloc.dart';

const _kBlue = Color(0xFF1565C0);
const _kOrange = Color(0xFFF57C00);
const _kGreen = Color(0xFF2E7D32);

/// Formulaire de saisie d'une nouvelle commande en 3 étapes :
///
///  1. Sélection des articles (depuis [LocalBusinessItem] chargés via BLoC)
///  2. Saisie de la référence (plaque ou numéro de ticket)
///  3. Récapitulatif + validation
class NewOrderScreen extends StatefulWidget {
  final LocalBusinessesData business;
  final String userId;

  const NewOrderScreen({
    super.key,
    required this.business,
    required this.userId,
  });

  @override
  State<NewOrderScreen> createState() => _NewOrderScreenState();
}

class _NewOrderScreenState extends State<NewOrderScreen> {
  final _pageController = PageController();
  final _refController = TextEditingController();

  int _step = 0;

  /// Panier : businessItemId → OrderItemInput
  final Map<String, OrderItemInput> _basket = {};

  int get _total => _basket.values.fold(0, (s, i) => s + i.subtotal);

  bool get _basketEmpty => _basket.values.every((i) => i.quantity == 0);

  @override
  void initState() {
    super.initState();
    context
        .read<OrderBloc>()
        .add(BusinessItemsRequested(widget.business.id));
  }

  @override
  void dispose() {
    _pageController.dispose();
    _refController.dispose();
    super.dispose();
  }

  // ──────────────────────────────────────────────────────────────────
  // Navigation entre étapes
  // ──────────────────────────────────────────────────────────────────

  void _next() {
    if (_step < 2) {
      setState(() => _step++);
      _pageController.animateToPage(
        _step,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    }
  }

  void _back() {
    if (_step > 0) {
      setState(() => _step--);
      _pageController.animateToPage(
        _step,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    } else {
      Navigator.pop(context);
    }
  }

  void _validate() {
    final items =
        _basket.values.where((i) => i.quantity > 0).toList();
    if (items.isEmpty) return;

    context.read<OrderBloc>().add(
          OrderCreateRequested(
            businessId: widget.business.id,
            userId: widget.userId,
            reference: _refController.text.trim().isEmpty
                ? '—'
                : _refController.text.trim(),
            items: items,
          ),
        );
    Navigator.pop(context);
  }

  // ──────────────────────────────────────────────────────────────────
  // Build
  // ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final isWash = widget.business.businessType == 'WASH';

    return Scaffold(
      backgroundColor: const Color(0xFFF4F6FA),
      appBar: AppBar(
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF1A1A2E),
        elevation: 1,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded),
          onPressed: _back,
        ),
        title: Text(
          isWash ? 'Nouvelle Voiture' : 'Nouveau Service',
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        actions: [
          // Indicateur d'étape textuel
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Text(
              'Étape ${_step + 1}/3',
              style: const TextStyle(
                  color: Color(0xFF90A4AE), fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Indicateur de progression ──────────────────────
          _StepIndicator(step: _step),

          // ── Contenu paginé ─────────────────────────────────
          Expanded(
            child: BlocBuilder<OrderBloc, OrderState>(
              builder: (context, state) {
                final items = state is BusinessItemsLoaded
                    ? state.items
                    : <LocalBusinessItem>[];

                return PageView(
                  controller: _pageController,
                  physics: const NeverScrollableScrollPhysics(),
                  children: [
                    // Étape 1 : Sélection des articles
                    _ItemSelectionPage(
                      items: items,
                      isLoading: state is OrderLoading,
                      basket: _basket,
                      isWash: isWash,
                      onChanged: () => setState(() {}),
                    ),

                    // Étape 2 : Référence
                    _ReferencePage(
                      controller: _refController,
                      isWash: isWash,
                    ),

                    // Étape 3 : Récapitulatif
                    _SummaryPage(
                      basket: _basket,
                      reference: _refController.text,
                      total: _total,
                    ),
                  ],
                );
              },
            ),
          ),

          // ── Barre de navigation ────────────────────────────
          _BottomBar(
            step: _step,
            canNext: _step == 0 ? !_basketEmpty : true,
            canValidate: !_basketEmpty,
            total: _total,
            onNext: _next,
            onValidate: _validate,
            onBack: _back,
          ),
        ],
      ),
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// Indicateur d'étape
// ──────────────────────────────────────────────────────────────────

class _StepIndicator extends StatelessWidget {
  final int step;
  const _StepIndicator({required this.step});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      child: Row(
        children: [
          _StepDot(index: 0, current: step, label: 'Articles'),
          _StepLine(active: step >= 1),
          _StepDot(index: 1, current: step, label: 'Référence'),
          _StepLine(active: step >= 2),
          _StepDot(index: 2, current: step, label: 'Valider'),
        ],
      ),
    );
  }
}

class _StepDot extends StatelessWidget {
  final int index, current;
  final String label;
  const _StepDot(
      {required this.index, required this.current, required this.label});

  @override
  Widget build(BuildContext context) {
    final done = current > index;
    final active = current == index;
    return Column(
      children: [
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          width: 32,
          height: 32,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: done || active ? _kBlue : const Color(0xFFE0E0E0),
          ),
          child: Center(
            child: done
                ? const Icon(Icons.check, color: Colors.white, size: 16)
                : Text(
                    '${index + 1}',
                    style: TextStyle(
                      color: active ? Colors.white : const Color(0xFF90A4AE),
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 10,
            color: active ? _kBlue : const Color(0xFF90A4AE),
            fontWeight: active ? FontWeight.w700 : FontWeight.normal,
          ),
        ),
      ],
    );
  }
}

class _StepLine extends StatelessWidget {
  final bool active;
  const _StepLine({required this.active});

  @override
  Widget build(BuildContext context) => Expanded(
        child: Container(
          height: 2,
          margin: const EdgeInsets.only(bottom: 18),
          color: active ? _kBlue : const Color(0xFFE0E0E0),
        ),
      );
}

// ──────────────────────────────────────────────────────────────────
// Étape 1 : Sélection des articles
// ──────────────────────────────────────────────────────────────────

class _ItemSelectionPage extends StatelessWidget {
  final List<LocalBusinessItem> items;
  final bool isLoading;
  final Map<String, OrderItemInput> basket;
  final bool isWash;
  final VoidCallback onChanged;

  const _ItemSelectionPage({
    required this.items,
    required this.isLoading,
    required this.basket,
    required this.isWash,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (items.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inventory_2_outlined,
                size: 56, color: Color(0xFFB0BEC5)),
            SizedBox(height: 12),
            Text('Aucun article configuré',
                style: TextStyle(color: Color(0xFF90A4AE))),
            SizedBox(height: 6),
            Text(
              'Ajoutez des articles depuis le panneau admin.',
              style: TextStyle(fontSize: 12, color: Color(0xFFB0BEC5)),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          isWash ? 'Que réalise-t-on ?' : 'Quels articles ?',
          style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Color(0xFF1A1A2E)),
        ),
        const SizedBox(height: 4),
        const Text('Appuyez pour ajouter, maintenez pour retirer.',
            style: TextStyle(fontSize: 12, color: Color(0xFF90A4AE))),
        const SizedBox(height: 16),
        ...items.map(
          (item) => _ItemCard(
            item: item,
            input: basket[item.id],
            onAdd: () {
              final current = basket[item.id];
              if (current == null) {
                basket[item.id] = OrderItemInput(
                  businessItemId: item.id,
                  name: item.name,
                  unitPrice: item.unitPrice,
                );
              } else {
                current.quantity++;
              }
              onChanged();
            },
            onRemove: () {
              final current = basket[item.id];
              if (current != null && current.quantity > 0) {
                current.quantity--;
                if (current.quantity == 0) basket.remove(item.id);
              }
              onChanged();
            },
          ),
        ),
      ],
    );
  }
}

class _ItemCard extends StatelessWidget {
  final LocalBusinessItem item;
  final OrderItemInput? input;
  final VoidCallback onAdd;
  final VoidCallback onRemove;

  const _ItemCard({
    required this.item,
    required this.input,
    required this.onAdd,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    final qty = input?.quantity ?? 0;
    final selected = qty > 0;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: selected
            ? _kBlue.withValues(alpha: 0.06)
            : Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: selected ? _kBlue : const Color(0xFFE0E0E0),
          width: selected ? 2 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.name,
                      style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: selected
                              ? _kBlue
                              : const Color(0xFF1A1A2E))),
                  const SizedBox(height: 2),
                  Text(Fmt.fcfa(item.unitPrice),
                      style: const TextStyle(
                          fontSize: 13, color: Color(0xFF607D8B))),
                ],
              ),
            ),
            // Contrôle quantité
            Row(
              children: [
                if (selected) ...[
                  _CounterBtn(
                    icon: Icons.remove,
                    onTap: onRemove,
                    color: const Color(0xFF90A4AE),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Text(
                      '$qty',
                      style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: _kBlue),
                    ),
                  ),
                ],
                _CounterBtn(
                  icon: Icons.add,
                  onTap: onAdd,
                  color: _kBlue,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CounterBtn extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;
  final Color color;

  const _CounterBtn(
      {required this.icon, required this.onTap, required this.color});

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Icon(icon, size: 18, color: color),
        ),
      );
}

// ──────────────────────────────────────────────────────────────────
// Étape 2 : Référence
// ──────────────────────────────────────────────────────────────────

class _ReferencePage extends StatelessWidget {
  final TextEditingController controller;
  final bool isWash;

  const _ReferencePage({required this.controller, required this.isWash});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 20),
        Icon(
          isWash ? Icons.directions_car_rounded : Icons.confirmation_number_outlined,
          size: 56,
          color: _kBlue,
        ),
        const SizedBox(height: 20),
        Text(
          isWash ? 'Plaque d\'immatriculation' : 'Numéro de ticket',
          style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: Color(0xFF1A1A2E)),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 8),
        Text(
          isWash
              ? 'Entrez la plaque du véhicule (facultatif)'
              : 'Entrez la référence du client (facultatif)',
          style: const TextStyle(fontSize: 14, color: Color(0xFF90A4AE)),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 32),
        TextField(
          controller: controller,
          autofocus: true,
          textCapitalization: TextCapitalization.characters,
          textAlign: TextAlign.center,
          style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              letterSpacing: 3),
          decoration: InputDecoration(
            hintText: isWash ? 'AA-001-B' : 'TKT-001',
            hintStyle: const TextStyle(
                color: Color(0xFFB0BEC5), letterSpacing: 2),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(16),
              borderSide: const BorderSide(color: Color(0xFFE0E0E0)),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(16),
              borderSide: const BorderSide(color: _kBlue, width: 2),
            ),
            contentPadding: const EdgeInsets.symmetric(
                horizontal: 20, vertical: 18),
          ),
        ),
      ],
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// Étape 3 : Récapitulatif
// ──────────────────────────────────────────────────────────────────

class _SummaryPage extends StatelessWidget {
  final Map<String, OrderItemInput> basket;
  final String reference;
  final int total;

  const _SummaryPage({
    required this.basket,
    required this.reference,
    required this.total,
  });

  @override
  Widget build(BuildContext context) {
    final items =
        basket.values.where((i) => i.quantity > 0).toList();

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text(
          'Récapitulatif',
          style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: Color(0xFF1A1A2E)),
        ),
        const SizedBox(height: 16),

        // Référence
        if (reference.trim().isNotEmpty) ...[
          _SummaryRow(
            label: 'Référence',
            value: reference.trim(),
            isBold: false,
          ),
          const Divider(height: 24),
        ],

        // Articles
        ...items.map(
          (item) => _SummaryRow(
            label: '${item.name} × ${item.quantity}',
            value: Fmt.fcfa(item.subtotal),
          ),
        ),

        const Divider(height: 24),

        // Total
        _SummaryRow(
          label: 'TOTAL',
          value: Fmt.fcfa(total),
          isBold: true,
          valueColor: _kGreen,
        ),
      ],
    );
  }
}

class _SummaryRow extends StatelessWidget {
  final String label, value;
  final bool isBold;
  final Color? valueColor;

  const _SummaryRow({
    required this.label,
    required this.value,
    this.isBold = true,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: isBold ? 16 : 14,
                fontWeight:
                    isBold ? FontWeight.w700 : FontWeight.normal,
                color: isBold
                    ? const Color(0xFF1A1A2E)
                    : const Color(0xFF607D8B),
              ),
            ),
            Text(
              value,
              style: TextStyle(
                fontSize: isBold ? 18 : 14,
                fontWeight:
                    isBold ? FontWeight.w800 : FontWeight.w600,
                color: valueColor ?? const Color(0xFF1A1A2E),
              ),
            ),
          ],
        ),
      );
}

// ──────────────────────────────────────────────────────────────────
// Barre de navigation du bas
// ──────────────────────────────────────────────────────────────────

class _BottomBar extends StatelessWidget {
  final int step;
  final bool canNext, canValidate;
  final int total;
  final VoidCallback onNext, onValidate, onBack;

  const _BottomBar({
    required this.step,
    required this.canNext,
    required this.canValidate,
    required this.total,
    required this.onNext,
    required this.onValidate,
    required this.onBack,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
      child: Row(
        children: [
          if (step > 0) ...[
            OutlinedButton(
              onPressed: onBack,
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: Color(0xFFE0E0E0)),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
                padding: const EdgeInsets.symmetric(
                    horizontal: 20, vertical: 14),
              ),
              child: const Icon(Icons.arrow_back_ios_new_rounded,
                  size: 18, color: Color(0xFF607D8B)),
            ),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: SizedBox(
              height: 54,
              child: ElevatedButton(
                onPressed: step < 2
                    ? (canNext ? onNext : null)
                    : (canValidate ? onValidate : null),
                style: ElevatedButton.styleFrom(
                  backgroundColor:
                      step < 2 ? _kBlue : _kOrange,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                  elevation: 3,
                ),
                child: step < 2
                    ? const Text('Suivant',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600))
                    : Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.check_circle_outline, size: 20),
                          const SizedBox(width: 8),
                          Text(
                            'Valider · ${Fmt.fcfa(total)}',
                            style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
