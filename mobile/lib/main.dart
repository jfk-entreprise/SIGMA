import 'package:drift/drift.dart' show Value;
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/data/local/sync_dao.dart';
import 'package:sigma_app/logic/bloc/auth/auth_bloc.dart';
import 'package:sigma_app/logic/bloc/orders/order_bloc.dart';
import 'package:sigma_app/presentation/screens/dashboard_screen.dart';
import 'package:sigma_app/presentation/screens/pin_screen.dart';

// ──────────────────────────────────────────────────────────────────
// Observer de cycle de vie — re-verrouille après inactivité
// ──────────────────────────────────────────────────────────────────

class _LifecycleLockObserver extends StatefulWidget {
  final Widget child;
  const _LifecycleLockObserver({required this.child});

  @override
  State<_LifecycleLockObserver> createState() => _LifecycleLockObserverState();
}

class _LifecycleLockObserverState extends State<_LifecycleLockObserver>
    with WidgetsBindingObserver {
  DateTime? _backgroundAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      _backgroundAt = DateTime.now();
    } else if (state == AppLifecycleState.resumed &&
        _backgroundAt != null) {
      final elapsed =
          DateTime.now().difference(_backgroundAt!).inSeconds;
      _backgroundAt = null;
      if (elapsed >= AuthBloc.kSessionTimeoutSeconds) {
        context.read<AuthBloc>().add(const AuthLockRequested());
      }
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final db = AppDatabase();
  await _seedDemoIfEmpty(db);
  runApp(SigmaApp(db: db));
}

// ──────────────────────────────────────────────────────────────────
// Données de démo (insérées une seule fois si la base est vide)
// ──────────────────────────────────────────────────────────────────

Future<void> _seedDemoIfEmpty(AppDatabase db) async {
  final existing = await (db.select(db.localBusinesses)..limit(1)).get();
  if (existing.isNotEmpty) return;

  const uid = 'demo-user-id';
  const bid = 'demo-business-id';

  await db.into(db.localUsers).insertOnConflictUpdate(
        LocalUsersCompanion.insert(
          id: uid,
          phoneNumber: '+22300000000',
          fullName: const Value('Mamadou Diallo'),
        ),
      );

  await db.into(db.localBusinesses).insertOnConflictUpdate(
        LocalBusinessesCompanion.insert(
          id: bid,
          name: 'Sigma Wash Express',
          businessType: 'WASH',
          ownerId: uid,
        ),
      );

  const items = [
    ('moto', 'Moto', 1500),
    ('berline', 'Berline', 3000),
    ('4x4', 'Pickup / 4x4', 4500),
    ('aspirateur', 'Aspirateur', 1000),
    ('moteur', 'Moteur complet', 2500),
  ];

  for (final (slug, name, price) in items) {
    await db.into(db.localBusinessItems).insertOnConflictUpdate(
          LocalBusinessItemsCompanion.insert(
            id: 'item-$slug',
            businessId: bid,
            name: name,
            unitPrice: price,
          ),
        );
  }
}

// ──────────────────────────────────────────────────────────────────
// Application
// ──────────────────────────────────────────────────────────────────

class SigmaApp extends StatelessWidget {
  final AppDatabase db;
  const SigmaApp({super.key, required this.db});

  @override
  Widget build(BuildContext context) {
    final syncDao = SyncQueueDao(db);

    return MultiBlocProvider(
      providers: [
        BlocProvider<AuthBloc>(
          create: (_) => AuthBloc(db: db)..add(const AuthStarted()),
        ),
        BlocProvider<OrderBloc>(
          create: (_) => OrderBloc(db: db, syncDao: syncDao),
        ),
      ],
      child: MaterialApp(
        title: 'SIGMA',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF1565C0),
          ),
          useMaterial3: true,
        ),
        home: const _LifecycleLockObserver(child: _RootRouter()),
      ),
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// Routeur racine piloté par AuthBloc
// ──────────────────────────────────────────────────────────────────

class _RootRouter extends StatelessWidget {
  const _RootRouter();

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<AuthBloc, AuthState>(
      builder: (context, state) => switch (state) {
        AuthAuthenticated(:final business, :final user) =>
          DashboardScreen(business: business, user: user),
        AuthNoData() => const _NoDataScreen(),
        AuthLoading() => const _SplashScreen(),
        _ => const PinScreen(),
      },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
}

class _NoDataScreen extends StatelessWidget {
  const _NoDataScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Color(0xFFF4F6FA),
      body: Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off_rounded,
                  size: 72, color: Color(0xFFB0BEC5)),
              SizedBox(height: 16),
              Text(
                'Aucun commerce trouvé',
                style: TextStyle(
                    fontSize: 20, fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 8),
              Text(
                'Connectez-vous au réseau pour synchroniser votre compte.',
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: Color(0xFF90A4AE), fontSize: 14),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
