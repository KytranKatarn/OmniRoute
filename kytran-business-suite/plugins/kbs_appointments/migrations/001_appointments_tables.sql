-- Appointments plugin tables (tenant schema, no tenant_id column)

CREATE TABLE IF NOT EXISTS appointment_types (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    description      TEXT,
    duration_minutes INT          DEFAULT 60,
    price            DECIMAL(10, 2),
    color            VARCHAR(7)   DEFAULT '#00e5ff',
    is_active        BOOLEAN      DEFAULT TRUE,
    created_at       TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS availability_slots (
    id           SERIAL PRIMARY KEY,
    day_of_week  INT       NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time   TIME      NOT NULL,
    end_time     TIME      NOT NULL,
    is_active    BOOLEAN   DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS appointments (
    id                   SERIAL PRIMARY KEY,
    customer_id          INT REFERENCES crm_customers (id) ON DELETE SET NULL,
    appointment_type_id  INT NOT NULL REFERENCES appointment_types (id) ON DELETE RESTRICT,
    title                VARCHAR(255) NOT NULL,
    start_time           TIMESTAMP    NOT NULL,
    end_time             TIMESTAMP    NOT NULL,
    status               VARCHAR(20)  DEFAULT 'scheduled'
                         CHECK (status IN ('scheduled', 'confirmed', 'in_progress', 'completed', 'cancelled', 'no_show')),
    notes                TEXT,
    metadata             JSONB        DEFAULT '{}',
    created_at           TIMESTAMP    DEFAULT NOW(),
    updated_at           TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appointments_customer_id        ON appointments (customer_id);
CREATE INDEX IF NOT EXISTS idx_appointments_start_time         ON appointments (start_time);
CREATE INDEX IF NOT EXISTS idx_appointments_status             ON appointments (status);
CREATE INDEX IF NOT EXISTS idx_appointments_appointment_type_id ON appointments (appointment_type_id);
