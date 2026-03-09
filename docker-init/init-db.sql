
-- This script runs automatically the FIRST time PostgreSQL starts.
-- It creates our data warehouse database alongside the Airflow metadata DB.

-- Create the warehouse database
CREATE DATABASE outbreaklens;

-- Connect to it and create schemas for our medallion layers
\c outbreaklens;

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;