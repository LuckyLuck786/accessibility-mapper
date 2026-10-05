-- Runs once on first container start (docker-entrypoint-initdb.d).
-- The API also runs the same DDL idempotently on boot, so either path works.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Helpful for the proximity queries in barrier_service (ST_DWithin fallback).
CREATE EXTENSION IF NOT EXISTS btree_gist;
