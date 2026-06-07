import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/core/utils/formatters.dart';
import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/logic/bloc/orders/order_bloc.dart';
import 'package:sigma_app/presentation/screens/new_order_screen.dart';
import 'package:sigma_app/presentation/screens/waiting_list_screen.dart';

const _kBlue = Color(0xFF1565C0);
const _kOrange = Color(0xFFF57C00);
const _kGreen = Color(0xFF2E7D32);
const _kRed = Color(0xFFC62828);
const _kBg = Color(0xFFF4F6FA);

class DashboardScreen extends StatefulWidget {
  final LocalBusinessesData business;
  final LocalUser? user;

  const DashboardScreen({super.key, required this.business, this.user});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() =>
      context.read<OrderBloc>().add(OrderDashboardRequested(widget.business.id));

  @override
  Widget build(BuildContext context) {
    final isWash = widget.business.businessType == 'WASH';
    final name = widget.user?.fullName ?? widget.business.name;

    return Scaffold(
      backgroundColor: _kBg,
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
            _refresh();
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
          return SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // ── En-tête ─────────────────────────────────────
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Bonjour 👋',
                                style: TextStyle(
                                    fontSize: 13, color: Color(0xFF607D8B))),
                            const SizedBox(height: 2),
                            Text(
                              widget.business.name,
                              style: const TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w700,
                                color: Color(0xFF1A1A2E),
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                      CircleAvatar(
                        backgroundColor: _kBlue,
                        radius: 22,
                        child: Text(
                          (name.isNotEmpty ? name[0] : 'S').toUpperCase(),
                          style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 18),
                        ),
                      ),
                    ],
                  ),
                ),

                // ── Carte KPI ──────────────────────────────────
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: _KpiCard(state: state),
                ),

                const SizedBox(height: 20),

                // ── Section "En attente" ───────────────────────
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'En attente',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: Color(0xFF1A1A2E),
                        ),
                      ),
                      TextButton(
                        onPressed: () => Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => BlocProvider.value(
                              value: context.read<OrderBloc>(),
                              child: WaitingListScreen(
                                business: widget.business,
                                user: widget.user,
                              ),
                            ),
                          ),
                        ).then((_) => _refresh()),
                        child: const Text('Voir tout',
                            style: TextStyle(color: _kBlue)),
                      ),
                    ],
                  ),
                ),

                // ── Liste commandes ────────────────────────────
                Expanded(
                  child: _OrderList(state: state, maxItems: 5),
                ),

                // ── Bouton CTA ─────────────────────────────────
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                  child: SizedBox(
                    width: double.infinity,
                    height: 58,
                    child: ElevatedButton.icon(
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => BlocProvider.value(
                            value: context.read<OrderBloc>(),
                            child: NewOrderScreen(
                              business: widget.business,
                              userId: widget.user?.id ?? 'unknown',
                            ),
                          ),
                        ),
                      ).then((_) => _refresh()),
                      icon: Icon(
                        isWash
                            ? Icons.directions_car_rounded
                            : Icons.dry_cleaning_rounded,
                        size: 24,
                      ),
                      label: Text(
                        isWash ? 'Nouvelle Voiture' : 'Nouveau Service',
                        style: const TextStyle(
                            fontSize: 17, fontWeight: FontWeight.w600),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _kOrange,
                        foregroundColor: Colors.white,
                        elevation: 4,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16)),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// Carte KPI
// ──────────────────────────────────────────────────────────────────

class _KpiCard extends StatelessWidget {
  final OrderState state;
  const _KpiCard({required this.state});

  @override
  Widget build(BuildContext context) {
    final dash = state is DashboardLoaded ? state as DashboardLoaded : null;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [
          BoxShadow(
              color: Colors.black12, blurRadius: 12, offset: Offset(0, 4))
        ],
      ),
      child: Row(
        children: [
          _KpiTile(
              label: 'CA Net',
              amount: dash?.netIncome ?? 0,
              color: _kGreen),
          _divider(),
          _KpiTile(
              label: 'Dépenses',
              amount: dash?.totalExpenses ?? 0,
              color: const Color(0xFF455A64)),
          _divider(),
          _KpiTile(
              label: 'Crédits',
              amount: dash?.totalCredits ?? 0,
              color: _kRed),
        ],
      ),
    );
  }

  Widget _divider() => Container(
        width: 1,
        height: 40,
        margin: const EdgeInsets.symmetric(horizontal: 8),
        color: const Color(0xFFE0E0E0),
      );
}

class _KpiTile extends StatelessWidget {
  final String label;
  final int amount;
  final Color color;

  const _KpiTile(
      {required this.label, required this.amount, required this.color});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(label,
              style:
                  const TextStyle(fontSize: 11, color: Color(0xFF90A4AE))),
          const SizedBox(height: 4),
          Text(
            Fmt.fcfa(amount),
            style: TextStyle(
                fontSize: 13, fontWeight: FontWeight.w700, color: color),
            textAlign: TextAlign.center,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// Liste des commandes
// ──────────────────────────────────────────────────────────────────

class _OrderList extends StatelessWidget {
  final OrderState state;
  final int maxItems;

  const _OrderList({required this.state, required this.maxItems});

  @override
  Widget build(BuildContext context) {
    if (state is OrderLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    final orders = state is DashboardLoaded
        ? (state as DashboardLoaded).pendingOrders.take(maxItems).toList()
        : <LocalServiceOrder>[];

    if (orders.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.hourglass_empty_rounded,
                size: 48, color: Color(0xFFB0BEC5)),
            SizedBox(height: 8),
            Text('Aucune commande en attente',
                style: TextStyle(color: Color(0xFF90A4AE))),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      itemCount: orders.length,
      itemBuilder: (context, i) => _OrderTile(order: orders[i]),
    );
  }
}

class _OrderTile extends StatelessWidget {
  final LocalServiceOrder order;
  const _OrderTile({required this.order});

  @override
  Widget build(BuildContext context) {
    final initial = order.vehicleNumber.isNotEmpty
        ? order.vehicleNumber[0].toUpperCase()
        : '?';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        boxShadow: const [
          BoxShadow(
              color: Colors.black12, blurRadius: 8, offset: Offset(0, 2))
        ],
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: const Color(0xFFE3F2FD),
            radius: 22,
            child: Text(initial,
                style: const TextStyle(
                    color: _kBlue,
                    fontWeight: FontWeight.bold,
                    fontSize: 16)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(order.vehicleNumber,
                    style: const TextStyle(
                        fontWeight: FontWeight.w700, fontSize: 15)),
                const SizedBox(height: 2),
                Text(Fmt.dateTime(order.createdAt),
                    style: const TextStyle(
                        fontSize: 12, color: Color(0xFF90A4AE))),
              ],
            ),
          ),
          Text(
            Fmt.fcfa(order.total),
            style: const TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 14,
                color: Color(0xFF1A1A2E)),
          ),
        ],
      ),
    );
  }
}
