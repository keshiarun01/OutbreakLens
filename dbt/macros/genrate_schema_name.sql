
/*
  Custom schema name macro
  ────────────────────────
  By default, dbt creates schemas as: <default_schema>_<custom_schema>
  So with default "silver" and custom "silver", you get "silver_silver".

  This macro overrides that behavior:
    - If a custom schema is set → use ONLY the custom schema name
    - If no custom schema → use the default schema

  This gives us clean schema names: bronze, silver, gold
*/

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}