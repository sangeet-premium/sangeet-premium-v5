import time
import psycopg2
from database.database import get_pg_connection, logger

def wait_for_db():
    """
    Continuously attempts to connect to the PostgreSQL database until a connection
    is established.
    """
    while True:
        try:
            conn = get_pg_connection()
            # If the connection is successful, close it and break the loop.
            conn.close()
            logger.info("Database is ready to accept connections.")
            from database import database #importing the database module and initializing it 
            database.init_postgres_db() 
            break
        except psycopg2.Error as e:
            logger.error(f"Database not ready yet: {e}")
            
            time.sleep(4)
            
    
  