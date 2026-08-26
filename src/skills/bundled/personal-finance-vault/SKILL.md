---
name: personal-finance-vault
description: Use when the user wants private account, transaction, import, categorization, recurring expense, budget, savings goal, asset, net-worth, income/expense report, bank-sync, currency, or finance-security workflows in the self-hosted personal finance vault.
version: 1.0.0
user-invocable: true
allowed-tools:
  - PersonalFinanceVault
---

# Personal finance vault

Use `PersonalFinanceVault` to check, install, start, stop, or diagnose the independently isolated finance service. Once running, direct the user to its local URL in Jonathan's preview pane for account setup and sensitive financial data entry.

Keep these boundaries:

- Treat all financial records and provider credentials as sensitive local data.
- Never request bank credentials in ordinary chat; use the vault's local protected forms.
- Never present forecasts as guaranteed outcomes or submit trades from this skill.
- No subscription, token payment, or paid connector is required by Jonathan. Third-party bank-data providers may impose their own terms.
- Ask before installing Docker, starting containers, enabling a bank connection, importing records, or changing stored finance data.
- Prefer read-only analysis and exports. State the source, date range, currency, and known gaps.
- Keep the AGPL service in its managed checkout; do not copy its source into Jonathan's MIT runtime.
