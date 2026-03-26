-- Limo Service plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Fleet vehicles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS limo_vehicles (
    id                 SERIAL PRIMARY KEY,
    name               VARCHAR(255) NOT NULL,
    vehicle_type       VARCHAR(50) NOT NULL
                           CHECK (vehicle_type IN (
                               'sedan', 'suv', 'stretch_limo', 'party_bus', 'van', 'other'
                           )),
    make               VARCHAR(100),
    model              VARCHAR(100),
    year               INTEGER,
    license_plate      VARCHAR(20),
    capacity           INTEGER,
    status             VARCHAR(20) DEFAULT 'available'
                           CHECK (status IN (
                               'available', 'booked', 'in_service', 'maintenance', 'retired'
                           )),
    mileage            INTEGER DEFAULT 0,
    last_service_date  DATE,
    next_service_date  DATE,
    features           JSONB DEFAULT '[]',
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Drivers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS limo_drivers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    license_number  VARCHAR(100),
    license_expiry  DATE,
    phone           VARCHAR(50),
    email           VARCHAR(255),
    status          VARCHAR(20) DEFAULT 'available'
                        CHECK (status IN ('available', 'on_trip', 'off_duty')),
    rating          DECIMAL(3,2) DEFAULT 5.0,
    total_trips     INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Bookings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS limo_bookings (
    id                       SERIAL PRIMARY KEY,
    customer_id              INTEGER,
    vehicle_id               INTEGER REFERENCES limo_vehicles(id),
    driver_id                INTEGER REFERENCES limo_drivers(id),
    booking_type             VARCHAR(50) NOT NULL
                                 CHECK (booking_type IN (
                                     'airport', 'corporate', 'wedding', 'prom',
                                     'hourly', 'point_to_point', 'other'
                                 )),
    pickup_address           TEXT NOT NULL,
    dropoff_address          TEXT,
    pickup_time              TIMESTAMP NOT NULL,
    estimated_duration_hours DECIMAL(4,1),
    actual_duration_hours    DECIMAL(4,1),
    passengers               INTEGER DEFAULT 1,
    status                   VARCHAR(20) DEFAULT 'pending'
                                 CHECK (status IN (
                                     'pending', 'confirmed', 'dispatched',
                                     'in_progress', 'completed', 'cancelled'
                                 )),
    base_fare                DECIMAL(10,2),
    extras                   DECIMAL(10,2) DEFAULT 0,
    total_fare               DECIMAL(10,2),
    payment_status           VARCHAR(20) DEFAULT 'unpaid'
                                 CHECK (payment_status IN ('unpaid', 'paid', 'refunded')),
    special_requests         TEXT,
    metadata                 JSONB DEFAULT '{}',
    created_at               TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Maintenance records
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS limo_maintenance (
    id                  SERIAL PRIMARY KEY,
    vehicle_id          INTEGER NOT NULL REFERENCES limo_vehicles(id),
    maintenance_type    VARCHAR(50) NOT NULL
                            CHECK (maintenance_type IN (
                                'oil_change', 'tire', 'brake', 'inspection',
                                'wash', 'detail', 'repair', 'other'
                            )),
    description         TEXT,
    cost                DECIMAL(10,2),
    performed_date      DATE,
    next_due_date       DATE,
    mileage_at_service  INTEGER,
    performed_by        VARCHAR(255),
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
