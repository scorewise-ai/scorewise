# ScoreWise AI - Database Configuration with Migration Support
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the DATABASE_URL environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable is not set. Please set it in your .env file or environment.")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all tables in the database"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        raise

def migrate_database():
    """Run database migrations for existing installations"""
    try:
        # Add new columns to existing users table if they don't exist
        migration_queries = [
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='stripe_customer_id') THEN
                    ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR UNIQUE;
                    CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id ON users(stripe_customer_id);
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='subscription_tier') THEN
                    ALTER TABLE users ADD COLUMN subscription_tier VARCHAR DEFAULT 'trial' NOT NULL;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='subscription_status') THEN
                    ALTER TABLE users ADD COLUMN subscription_status VARCHAR DEFAULT 'trialing' NOT NULL;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='stripe_subscription_id') THEN
                    ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR UNIQUE;
                    CREATE INDEX IF NOT EXISTS idx_users_stripe_subscription_id ON users(stripe_subscription_id);
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='current_period_start') THEN
                    ALTER TABLE users ADD COLUMN current_period_start TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='current_period_end') THEN
                    ALTER TABLE users ADD COLUMN current_period_end TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='trial_end') THEN
                    ALTER TABLE users ADD COLUMN trial_end TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='assignments_this_month') THEN
                    ALTER TABLE users ADD COLUMN assignments_this_month INTEGER DEFAULT 0 NOT NULL;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='usage_reset_date') THEN
                    ALTER TABLE users ADD COLUMN usage_reset_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='full_name') THEN
                    ALTER TABLE users ADD COLUMN full_name VARCHAR;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='is_active') THEN
                    ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE NOT NULL;
                END IF;
            END $$;
            """,
            """
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='updated_at') THEN
                    ALTER TABLE users ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL;
                END IF;
            END $$;
            """
        ]
        
        with engine.connect() as conn:
            for query in migration_queries:
                try:
                    conn.execute(text(query))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Migration query failed (might be expected): {str(e)}")
                    continue
        
        # Create new tables that might not exist
        Base.metadata.create_all(bind=engine)
        
        logger.info("✓ Database migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during migration: {str(e)}")
        raise

if __name__ == "__main__":
    # Run migrations when this script is executed directly
    migrate_database()
    logger.info("Migration completed!")