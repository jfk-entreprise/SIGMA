import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/core/utils/formatters.dart';
import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/logic/bloc/orders/order_bloc.dart';

const _kBlue = Color(0xFF1565C0);
const _kGreen = Color(0xFF2E7D32);
const _kRed = Color(0xFFC62828);
const _kOrange = Color(0xFFF57C00);

/// Écran de la file d'attente — toutes les commandes PENDING.
/// Un appui sur une carte ouvre un BottomSheet de paiement / annulation.
class WaitingListScreen extends StatelessWidget {
  final LocalBusinessesData business;
  final LocalUser? user;

  const WaitingListScreen({
    super.key,
    required this.business,
    this.user,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6FA),
      body: BlocConsumer<OrderBloc, OrderState>(
        listener: (context, state) {
          if (state is OrderActionSuccess) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(state.message),
                backgroundColor: _kGreen,
                behavior: SnackBarBehavior.floating,
              ),
            );
            context
                .read<OrderBloc>()
                .add(OrderDashboardRequested(business.id));
          } else if (state is OrderError) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(state.message),
                backgroundColor: _kRed,
                behavior: SnackBarBehavior.floating,
              ),
            );
          }
        },
        builder: (context, state) {
          final orders = state is DashboardLoaded
              ? state.pendingOrders
              : <LocalServiceOrder>[];

          return CustomScrollView(
            slivers: [
              SliverAppBar(
                pinned: true,
                backgroundColor: Colors.white,
                foregroundColor: const Color(0xFF1A1A2E),
                elevation: 1,
                title: Text(
                  orders.isEmpty
                      ? 'File d\'attente'
                      : 'File d\'attente (${orders.length})',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, fontSize: 18),
                ),
              ),
              if (state is OrderLoading)
                const SliverFillRemaining(
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (orders.isEmpty)
                const SliverFillRemaining(
                  child: Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.check_circle_outline_rounded,
                            size: 64, color: Color(0xFFB0BEC5)),
                        SizedBox(height: 12),
                        Text(
                          'Aucune commande en attente',
                          style: TextStyle(
                              fontSize: 16, color: Color(0xFF90A4AE)),
                        ),
                      ],
                    ),
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.all(16),
                  sliver: SliverList.builder(
                    itemCount: orders.length,
                    itemBuilder: (context, i) => _OrderCard(
                      order: orders[i],
                      onAction: (action) =>
                          _handleAction(context, orders[i], action),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  void _handleAction(
    BuildContext context,
    LocalServiceOrder order,
    _Action action,
  ) {
    switch (action) {
      case _Action.payCash:
        context.read<OrderBloc>().add(OrderPayRequested(
              orderId: order.id,
              businessId: business.id,
              method: PaymentMethod.cash,
            ));
      case _Action.payMobile:
        context.read<OrderBloc>().add(OrderPayRequested(
              orderId: order.id,
              businessId: business.id,
              method: PaymentMethod.mobileMoney,
            ));
      case _Action.cancel:
        context.read<OrderBloc>().add(OrderCancelRequested(
              orderId: order.id,
              businessId: business.id,
            ));
    }
  }
}

// ──────────────────────────────────────────────────────────────────
// Card commande
// ──────────────────────────────────────────────────────────────────

enum _Action { payCash, payMobile, cancel }

class _OrderCard extends StatelessWidget {
  final LocalServiceOrder order;
  final void Function(_Action) onAction;

  const _OrderCard({required this.order, required this.onAction});

  @override
  Widget build(BuildContext context) {
    final initial = order.vehicleNumber.isNotEmpty
        ? order.vehicleNumber[0].toUpperCase()
        : '?';

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _showSheet(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: const Color(0xFFE3F2FD),
                radius: 24,
                child: Text(initial,
                    style: const TextStyle(
                        color: _kBlue,
                        fontWeight: FontWeight.bold,
                        fontSize: 18)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(order.vehicleNumber,
                        style: const TextStyle(
                            fontWeight: FontWeight.w700, fontSize: 16)),
                    const SizedBox(height: 3),
                    Text(Fmt.dateTime(order.createdAt),
                        style: const TextStyle(
                            fontSize: 12, color: Color(0xFF90A4AE))),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(Fmt.fcfa(order.total),
                      style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 15,
                          color: Color(0xFF1A1A2E))),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: _kOrange.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text('EN ATTENTE',
                        style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: _kOrange)),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius:
              BorderRadius.vertical(top: Radius.circular(24))),
      builder: (sheetCtx) => _PaymentSheet(
        order: order,
        onAction: (action) {
          Navigator.pop(sheetCtx);
          onAction(action);
        },
      ),
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// BottomSheet paiement
// ──────────────────────────────────────────────────────────────────

class _PaymentSheet extends StatelessWidget {
  final LocalServiceOrder order;
  final void Function(_Action) onAction;

  const _PaymentSheet({required this.order, required this.onAction});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: const Color(0xFFE0E0E0),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 20),
          Text(order.vehicleNumber,
              style: const TextStyle(
                  fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(Fmt.fcfa(order.total),
              style: const TextStyle(
                  fontSize: 15, color: Color(0xFF607D8B))),
          const SizedBox(height: 24),
          _SheetTile(
            icon: Icons.payments_outlined,
            iconColor: _kGreen,
            label: 'Payer en espèces',
            onTap: () => onAction(_Action.payCash),
          ),
          const SizedBox(height: 10),
          _SheetTile(
            icon: Icons.phone_android_rounded,
            iconColor: _kBlue,
            label: 'Payer Mobile Money',
            onTap: () => onAction(_Action.payMobile),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 14),
            child: Divider(),
          ),
          _SheetTile(
            icon: Icons.cancel_outlined,
            iconColor: _kRed,
            label: 'Annuler la commande',
            labelColor: _kRed,
            onTap: () => onAction(_Action.cancel),
          ),
        ],
      ),
    );
  }
}

class _SheetTile extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String label;
  final Color labelColor;
  final VoidCallback onTap;

  const _SheetTile({
    required this.icon,
    required this.iconColor,
    required this.label,
    this.labelColor = const Color(0xFF1A1A2E),
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: iconColor.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          children: [
            Icon(icon, color: iconColor, size: 22),
            const SizedBox(width: 14),
            Text(label,
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: labelColor)),
          ],
        ),
      ),
    );
  }
}
