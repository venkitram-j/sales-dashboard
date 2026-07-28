"""
Shared DB connection, Postgres for dev and Neon for prod
"""

import os
import streamlit as st

from pathlib import Path


class DBConn:
    """Manages a shared database connection across all components."""
    
    def __init__(self, connection_name: str = "postgresql"):
        """Initializes the built-in Streamlit SQL connection."""
        if os.getenv("ENVIRONMENT", "dev") == "prod":
            connection_name = "neon"
        self.conn = st.connection(connection_name, type="sql")

    @st.cache_resource
    def init_schema(self):
        """Create tables/indexes if they don't exist yet"""
        with st.spinner("Loading database tables"):
            schema_path = Path(__file__).parent / "schema.sql"
            ddl = schema_path.read_text()
            with self.conn.session as s:
                s.execute(ddl)
                s.commit()

    def query(self, sql_query: str, ttl: str = "10m", **kwargs):
        """Reads data from the database with built-in caching."""
        return self.conn.query(sql_query, ttl=ttl, **kwargs)

    def execute(self, sql_statement: str, params: dict = None):
        """Writes, updates, or deletes data within a transaction."""
        with self.conn.session as session:
            session.execute(sql_statement, params)
            session.commit()
