-- Salon/Hairdressing industry plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Services (haircuts, colour treatments, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salon_services (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    category         VARCHAR(50) NOT NULL
                         CHECK (category IN (
                             'cut', 'color', 'treatment', 'styling',
                             'extensions', 'nails', 'waxing', 'facial', 'other'
                         )),
    duration_minutes INT DEFAULT 60,
    price            DECIMAL(10, 2),
    description      TEXT,
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Stylists
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salon_stylists (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    specialties     JSONB DEFAULT '[]',
    commission_rate DECIMAL(5, 2) DEFAULT 0,
    schedule        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT TRUE,
    bio             TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Bookings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salon_bookings (
    id           SERIAL PRIMARY KEY,
    customer_id  INT,
    stylist_id   INT REFERENCES salon_stylists (id) ON DELETE SET NULL,
    service_id   INT REFERENCES salon_services (id) ON DELETE SET NULL,
    booking_date DATE NOT NULL,
    start_time   TIME NOT NULL,
    end_time     TIME,
    status       VARCHAR(20) DEFAULT 'scheduled'
                     CHECK (status IN (
                         'scheduled', 'confirmed', 'in_chair',
                         'completed', 'cancelled', 'no_show'
                     )),
    notes        TEXT,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Product inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salon_product_inventory (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    brand        VARCHAR(100),
    category     VARCHAR(50)
                     CHECK (category IN (
                         'shampoo', 'conditioner', 'color', 'treatment',
                         'styling', 'tool', 'retail', 'other'
                     )),
    sku          VARCHAR(100),
    quantity     INT DEFAULT 0,
    min_quantity INT DEFAULT 3,
    retail_price DECIMAL(10, 2),
    cost_price   DECIMAL(10, 2),
    supplier     VARCHAR(255),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Client history (per-visit colour formulas, notes, photos)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salon_client_history (
    id           SERIAL PRIMARY KEY,
    customer_id  INT,
    stylist_id   INT,
    service_id   INT,
    visit_date   DATE,
    formula      TEXT,
    color_used   TEXT,
    notes        TEXT,
    photos       JSONB DEFAULT '[]',
    satisfaction INT CHECK (satisfaction BETWEEN 1 AND 5),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_salon_bookings_date       ON salon_bookings (booking_date);
CREATE INDEX IF NOT EXISTS idx_salon_bookings_stylist    ON salon_bookings (stylist_id);
CREATE INDEX IF NOT EXISTS idx_salon_bookings_customer   ON salon_bookings (customer_id);
CREATE INDEX IF NOT EXISTS idx_salon_bookings_status     ON salon_bookings (status);
CREATE INDEX IF NOT EXISTS idx_salon_services_category   ON salon_services (category);
CREATE INDEX IF NOT EXISTS idx_salon_services_active     ON salon_services (is_active);
CREATE INDEX IF NOT EXISTS idx_salon_inventory_category  ON salon_product_inventory (category);
CREATE INDEX IF NOT EXISTS idx_salon_history_customer    ON salon_client_history (customer_id);
CREATE INDEX IF NOT EXISTS idx_salon_history_visit       ON salon_client_history (visit_date);
