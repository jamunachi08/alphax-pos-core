# AlphaX POS Suite — Vertical Platform Edition

A complete vertical Point-of-Sale platform built on Frappe / ERPNext v15.
One install. One outlet record. Any combination of Restaurant, Cafe, Retail,
Grocery, Pharmacy, Salon, Service, and Generic running side-by-side on the
same terminal — through one beautiful, fully bilingual (English ↔ Arabic
with RTL) cashier UI.

---

## What's in this drop

### Multi-domain outlets — one solution for all

Every outlet declares an **Active Domains** list. A single outlet can run
Restaurant + Retail + Pharmacy at the same time. The cashier UI loads only
the modules that are actually enabled, driven by the Domain Pack registry.

`AlphaX POS Domain Pack` declares each domain's capabilities:
`uses_floor_plan`, `uses_kds`, `uses_modifiers`, `uses_recipes`, `uses_scale`,
`uses_batch_expiry`, `uses_serial`, `uses_appointments`, `uses_tips`,
`uses_service_charge`, `uses_courses`, `uses_table_qr`, `uses_split_bill`,
`uses_loyalty`, `uses_prescription`.

Eight packs are seeded on install. Add your own or change the flags on the
existing ones to fit your business.

### Cashier SPA — Vue 3, tablet-first, bilingual

A single-screen cashier UI lives at `/app/alphax-pos-v2`. It calls
`pos_boot` once on login and adapts the entire UI from that one payload:

- **One screen for every business.** A sidebar shows tabs for whichever
  domains the outlet runs (Restaurant, Café, Retail, Pharmacy, …). Tap a
  tab and the menu re-filters to that domain's items, while a contextual
  ribbon above the cart shows only the chips that domain needs (table for
  Restaurant, Rx capture for Pharmacy, batch picker for Grocery,
  appointment slot for Salon).
- **Bilingual, RTL-aware.** English ↔ Arabic with a one-tap locale switch.
  Every layout decision uses CSS logical properties (`margin-inline-start`,
  `inset-inline-end`) so the entire UI flips correctly under `dir="rtl"`.
  Numbers and currency formatting respect the active locale.
- **Modifier tree.** Beverage / food items open a modifier picker with
  required and optional groups (Size / Milk / Sugar / Extras), min/max
  constraints, and price deltas reflected in the running total.
- **Split bill.** Restaurant orders can be split by seat with per-seat
  totals.
- **Loyalty live.** Per-line earn rates show as you build the cart. Loyalty
  card scan, redemption preview, max-redemption-percent enforcement.
- **Multi-tender payment.** Cash + Card + MADA + STC in one transaction,
  with automatic change calculation and a numeric keypad.
- **Hold / recall** persisted in localStorage.
- **Scale-barcode parsing** for weighed items — a numeric scan at the
  search bar is matched against the configured prefix rules and added with
  its embedded weight or price.
- **Demo mode.** Append `?mock=1` to the URL or set
  `localStorage.alphax_mock = '1'` to run the full UI without a backend —
  useful for screenshots, demos, and frontend development.

### Loyalty engine with per-item earn rules

Multi-program. Per-item earn-rate overrides. Tier multipliers. Auditable
ledger that cannot drift from the wallet balance.

- `AlphaX POS Loyalty Program` — one program per business (you can run a
  separate program per domain via `domain_scope`).
- `AlphaX POS Loyalty Rule` (child) — Item / Item Group / Brand / Domain /
  No Earn rules with priority. Item beats Item Group beats Brand beats Domain
  by default; explicit `priority` breaks ties.
- `AlphaX POS Loyalty Tier` (child) — Bronze / Silver / Gold tiers with
  earn and redeem multipliers based on lifetime points.
- `AlphaX POS Loyalty Wallet` — one per (customer, program) with optional
  `card_number` for QR / barcode lookup.
- `AlphaX POS Loyalty Ledger` — submittable, GL-style audit trail of every
  Earn / Redeem / Expire / Adjust / Reverse entry.

The engine lives in `alphax_pos_suite.alphax_pos_suite.loyalty.engine`.
Whitelisted endpoints for the cashier:

```
loyalty.engine.quote_points(program, items, ...)        # live preview
loyalty.engine.lookup_wallet(card_number=..., ...)      # scan loyalty card
loyalty.engine.quote_redemption(program, customer, ...) # validate redemption
```

Auto-posting on Sales Invoice submit / cancel via
`alphax_pos_suite.alphax_pos_suite.loyalty.hooks`. Daily expiry job runs from
`scheduler_events.daily`.

### Visual floor plan designer

Replaces the static `Floor` / `Table` records with a real visual designer
at `/app/alphax-floor-designer`. Coordinates persist on `pos_x`, `pos_y`,
`width`, `height`, `rotation`. Live status broadcasts via
`frappe.publish_realtime` so every cashier station sees the same floor.

### KDS screen

Full-screen kitchen display at `/app/alphax-kds`. Filters by station,
listens for `alphax_pos_kds_new_ticket` events, plays a soft beep on new
tickets, color-codes overdue tickets, ticks SLA timers every 5 seconds.

### Hardware bridge — universal compatibility through configuration

Receipt printers, cash drawers, customer pole displays, and weighing
scales work through a small local daemon (`alphax-pos-bridge`) you
install once on the cashier device. **No vendor lock-in.** 19 hardware
profiles ship out of the box; for any device not in the list, write a
20-line YAML profile and you're done.

Card terminals follow the same pattern via a `terminal` device kind:
mock + Geidea + HyperPay + Network International + Payfort + generic-REST
adapters. Cashier picks "Card" in the payment dialog, the bridge sends
the charge to the configured terminal, the dialog blocks on a "waiting
on customer" overlay, and the terminal returns approved/declined with
auth code, masked PAN, and card brand — all stamped onto the receipt.
Real-network certification per provider needs sandbox credentials, but
the architecture and SPA wiring are done.

Connection types: USB, RS-232 / USB-to-serial, Ethernet (TCP), parallel
port, drawer-through-printer passthrough, plus cloud-mediated for card
terminals. Add a new connection or protocol with one Python class —
every existing device profile keeps working.

### Offline-aware sales

The cashier never gets blocked by a flaky network. `submitSale()` tries
online first; if the network drops, the sale is queued in IndexedDB
(keyed by a `client_uuid`) and the receipt still prints with an
"OFFLINE — will sync" footer. A background worker drains the queue
every 15 seconds whenever connectivity is back. Server-side dedupe via
`alphax_client_uuid` on Sales Invoice (with `unique:1, no_copy:1`) makes
retries safe — a duplicate UUID throws `DuplicateEntryError`, which the
SPA detects and treats as "already synced."

The sidebar's sync pill shows the live state: green when everything's
synced, amber when items are pending, red when something failed. Click
to open the queue inspector for retry/discard.

### Touch-mode polish

- Long-press a cart line (or right-click on desktop) to open the action
  sheet: set qty / discount % / note / void.
- Kiosk mode locks the page to fullscreen, blocks F5 / Ctrl-R / devtools
  shortcuts, and requires a 4-digit PIN to exit.
- Haptic feedback (`navigator.vibrate`) on every primary tap, with
  graceful no-op on iOS Safari and desktop.
- The search bar auto-refocuses after 3 seconds of idle anywhere on the
  page so HID barcode scanners always land in the right place.

### Unified `pos_boot` API

The cashier SPA calls one endpoint on login and gets everything: outlet,
active domain packs, capability flags (union), POS profile, theme, loyalty
programs, payment methods (with terminal-capture flags), scale rules, taxes,
currency, server time. Cached for five minutes per terminal.

### Bug fixes from v0

- **Recipe lookup field-name mismatch**: `compute_recipe_cost` was filtering
  `AlphaX POS Recipe` by `item` and reading child rows by `item_code` —
  both wrong. Fixed; now returns a per-material `breakdown` too.
- **Order idempotency**: `before_insert` checks for existing `client_uuid`
  and throws `DuplicateEntryError` instead of silently creating a second
  copy on offline-queue retry.
- **Secure QR ordering**: previously a public endpoint accepting any
  `item_code`. Now binds menu via outlet primary domain + default item
  group, looks up rate from Item Price (server-side), enforces line and
  qty limits, rate-limits per token.

---

## Install / Upgrade

Backend (Frappe / ERPNext):

```
bench --site <site> install-app alphax_pos_suite     # fresh
bench --site <site> migrate                          # upgrade
```

The migrate runs `patches/v15_0/upgrade_to_vertical_platform.py`. Idempotent.

Cashier SPA (Vue 3) — **no build step required**. The cashier UI ships
as plain `.vue` files inside the app and compiles in the browser. To
make the UI work fully offline, run the one-time vendor download:

```
bench --site <site> execute alphax_pos_suite.alphax_pos_suite.cashier.vendor.fetch_vendor_bundles
bench --site <site> clear-cache
```

This downloads Vue + Pinia + vue-i18n into `public/dist/vendor/` (~150 KB
total). Skip it and the cashier UI will fetch from a CDN on first page
load instead — still works, just needs internet on day one.

The cashier UI works on Frappe Cloud out of the box. **No `npm install`,
no Node, no Vite required to install or update.**

For SPA development with hot-reload (only needed if you want to actively
hack on the cashier UI itself):

```
cd apps/alphax_pos_suite/frontend
npm install
npm run dev      # Vite dev server with hot reload, proxies /api to localhost:8000
```

After dev changes, copy the modified `.vue` files into `public/dist/cashier/sfc/`
and they're live. (Or just edit them in `public/dist/cashier/sfc/` directly —
no rebuild needed, since the SFC loader compiles them at runtime.)

---

## Tests

```
bench --site <site> run-tests --app alphax_pos_suite
```

Coverage:

- `tests/test_loyalty_engine.py` — rule precedence, redemption caps,
  ledger atomicity
- `tests/test_pos_boot.py` — multi-domain feature union, fallback to Generic
- `tests/test_orders_and_recipes.py` — recipe cost bug fix, idempotent orders

---

## Frontend project structure

```
alphax_pos_suite/
├─ frontend/                    # Vue 3 source — the cashier SPA
│  ├─ package.json
│  ├─ vite.config.js            # outputs to ../alphax_pos_suite/public/dist/cashier/
│  ├─ index.html
│  └─ src/
│     ├─ main.js                # entry — applies dir/lang before mount
│     ├─ App.vue
│     ├─ views/CashierView.vue  # 3-column layout, modal orchestration
│     ├─ components/            # SidebarPanel, MenuPanel, CartPanel,
│     │                         # ContextRibbon, ModifierPicker, SplitBill,
│     │                         # PaymentDialog, CustomerPicker, LoyaltyScan,
│     │                         # TablePicker, RxCapture, HeldOrders,
│     │                         # BootScreen, AppModal, LocaleSwitch, Toaster
│     ├─ stores/pos.js          # Pinia store — single source of truth
│     ├─ api/
│     │  ├─ client.js           # frappe.call wrapper
│     │  └─ mock.js             # full mock dataset for ?mock=1 demos
│     ├─ composables/           # useMoney, modifiers
│     ├─ locales/               # en.js, ar.js, index.js
│     └─ styles/globals.css     # design tokens, logical properties
├─ alphax_pos_suite/             # Frappe app (Python)
│  ├─ boot/                      # pos_boot endpoint
│  ├─ floor/                     # floor designer API
│  ├─ loyalty/                   # earn/redeem engine + hooks
│  ├─ doctype/                   # all doctypes (loyalty, domain pack, …)
│  ├─ page/
│  │  ├─ alphax_pos_v2/          # thin loader for the Vue bundle
│  │  ├─ alphax_floor_designer/
│  │  └─ alphax_kds/
│  └─ public/dist/cashier/       # build output (gitignored)
├─ Makefile                      # `make build` builds the SPA
├─ package.json                  # `npm run build` from app root
└─ hooks.py                      # Frappe app hooks
```

---

## Architecture overview

```
Cashier SPA (Vue) / KDS / Manager web / Customer QR
                    ↓
   pos_boot(terminal)  → outlet, domain packs, features, payments, scale, theme
                    ↓
   Active domain packs decide which UI modules load
                    ↓
   Shared core: orders, carts, payments, inventory, recipes, BOM, shifts,
                tax, reporting, customers, loyalty, pricing, offers, audit
                    ↓
   ERPNext core: Sales Invoice · Stock Entry · Customer · Item · GL · ZATCA
```

---

## Roadmap

The following pieces depend on this foundation and are next:

1. ~~Cashier SPA tablet-first UI~~ — **shipped** as Vue 3 in `frontend/`.
2. ~~KDS screen~~ — **shipped** as `/app/alphax-kds`.
3. ~~Visual floor plan designer~~ — **shipped** as `/app/alphax-floor-designer`.
4. ~~Multi-domain outlets, loyalty engine, secure QR ordering~~ — **shipped**.
5. ~~Modifier tree, split bill, contextual ribbon~~ — **shipped**.
6. ~~Bilingual EN/AR with full RTL~~ — **shipped**.
7. ~~Hardware bridge with universal device compatibility~~ — **shipped**
   as `alphax-pos-bridge`. 19 built-in profiles. Full SPA integration:
   auto-print receipt, auto-kick drawer, cart-mirror to pole display,
   live weight chip, hardware settings dialog with one-click tests.
8. ~~Touch-mode polish~~ — **shipped**. Long-press cart actions, kiosk
   mode with PIN-protected exit, haptic feedback hooks, auto-focus to
   barcode field after idle.
9. ~~Offline queue~~ — **shipped**. IndexedDB-backed queue, sync worker
   with background drain, sync status pill, queue inspector modal,
   server-side dedupe via `alphax_client_uuid` on Sales Invoice.
10. ~~Card terminal architecture~~ — **shipped** as the bridge's
    `terminal` device kind. Mock + Geidea + HyperPay + Network
    International + Payfort + generic-REST adapters. SPA payment dialog
    routes card-style payment modes through the terminal automatically,
    captures auth code / masked PAN / brand on the receipt.

Next:

- Real card terminal certification per provider (Geidea, HyperPay,
  Network International, Payfort): each requires a merchant contract,
  sandbox credentials, and a provider-specific test plan. The adapters
  and SPA wiring are already in place — only the credentials and signing
  schemes (HMAC for Payfort, mTLS for some) remain.
- ZATCA Phase 2 e-invoicing (signed XML + QR on every invoice).
- Pharmacy pack: prescription validator, controlled-substance log, NPHIES.
- Salon pack: appointment calendar UI, staff scheduling, commissions.
- Additional locales (FR, ES, HI) — drop a file in `frontend/src/locales/`.
- Digital wallets: STC Pay, Apple Pay, MADA Pay (each via the same
  terminal-adapter pattern).

---

## License

MIT
