# Column Roles Reference

Standard roles that any project can use when mapping columns via
`save_column_profile`. Projects can extend with domain-specific roles.

## Universal Roles

| Role | Description | Detection Hints |
|------|-------------|-----------------|
| `identifier` | Unique ID column | dtype: object/int, values are unique |
| `label` | Human-readable name/title | dtype: object, descriptive text |
| `category` | Classification/grouping | dtype: object, few distinct values |
| `amount` | Primary quantitative value | dtype: float64/int64, site/location name in header |
| `metric` | Secondary quantitative value | dtype: float64, derived/calculated |
| `unit` | Unit of measurement | dtype: object, values like "kg", "L", "kWh" |
| `timestamp` | Date/time column | dtype: datetime64 or parseable date strings |
| `description` | Free text description | dtype: object, long text |
| `source` | Data origin reference | dtype: object, contains references |
| `unknown` | Could not determine | Use when ambiguous — ask user |

## Domain Extensions (Examples)

### LCI / Environmental

| Role | Description |
|------|-------------|
| `functional_unit` | FU-normalized value (e.g. "per ton crude oil") |
| `io` | Input/output classification |
| `process` | Process or activity name |
| `produced_from` | Origin/source material |

### Finance / Mortgage

| Role | Description |
|------|-------------|
| `borrower` | Person or entity name |
| `property` | Address or location |
| `loan_amount` | Principal value |
| `interest_rate` | Rate percentage |

### Analytics

| Role | Description |
|------|-------------|
| `dimension` | Grouping axis (region, product, channel) |
| `measure` | Aggregation target (revenue, count, duration) |
| `filter` | Filter/segment column |

## How to Infer Roles

When `extract_file_context` returns `profile_status: "needs_mapping"`:

1. **Look at dtype first**:
   - `float64` / `int64` → likely amount, metric, or FU
   - `object` → likely label, category, unit, or description
   - `datetime64` → timestamp

2. **Look at column name**:
   - Contains site/plant/location name → `amount` (site production data)
   - Contains "FU", "Functional Unit", "Per" → `functional_unit`
   - Contains "Total", "Amount", "Value", "Quantity" → `amount`
   - Contains "Category", "Type", "Class" → `category`
   - Contains "Unit", "UOM", "Satuan" → `unit`
   - Contains "Date", "Time", "Period" → `timestamp`

3. **Look at sample values**:
   - Few distinct values → `category`
   - All unique → `identifier` or `label`
   - Unit-like strings ("kg", "L", "ton") → `unit`

4. **When ambiguous** (e.g. two float64 columns):
   - Ask the user: "Which column should I use for analysis?"
   - Save the answer via `save_column_profile` for next time
