# XQL Grouping Rules for LCI IO Tables

XQL's ``xql_build_io_table`` groups rows differently per category to
reflect how LCA analysts think about each flow type.

## `material` (default)
Group rows by material name. Used for most input categories where the
same material may appear across several processes.

Example: "Diesel" for Generator A and Generator B collapse into a single
row "Diesel" with summed amounts.

## `produced_from`
Group rows by the `produced_from` column (source equipment or sub-process).
Used for fuel and air-emission categories where the equipment identity
matters more than the chemical name.

Example: Air Emissions from Boiler-1 stay separate from Boiler-2 even if
both produce CO2.

## `semantic`
Group by a coarser semantic bucket, typically applied manually to waste
streams where neither material nor source is enough.

Example: hazardous waste "Used Oil" and "Spent Catalyst" might both be
grouped under "Refining Maintenance Residues".

## Category Assignments (from `lci_rules.yaml`)

| Category              | Rule            |
|-----------------------|-----------------|
| Liquid Fuels          | produced_from   |
| Air Emissions         | produced_from   |
| Non-Hazardous Waste   | semantic        |
| Hazardous Waste       | semantic        |
| (any other)           | material        |
