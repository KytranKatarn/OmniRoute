-- Photography Studio plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Photo packages (service offerings)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photo_packages (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    includes          JSONB DEFAULT '[]',
    price             DECIMAL(10,2),
    duration_hours    DECIMAL(4,1),
    max_images        INTEGER,
    digital_delivery  BOOLEAN DEFAULT TRUE,
    print_included    BOOLEAN DEFAULT FALSE,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Photo shoots (booked sessions)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photo_shoots (
    id               SERIAL PRIMARY KEY,
    job_id           INTEGER,
    customer_id      INTEGER,
    shoot_type       VARCHAR(50) NOT NULL
                         CHECK (shoot_type IN (
                             'portrait', 'wedding', 'event', 'commercial',
                             'product', 'real_estate', 'other'
                         )),
    shoot_date       DATE,
    location         VARCHAR(255),
    duration_hours   DECIMAL(4,1),
    status           VARCHAR(20) DEFAULT 'booked'
                         CHECK (status IN (
                             'booked', 'confirmed', 'shot', 'editing',
                             'delivered', 'archived'
                         )),
    package_id       INTEGER,
    total_images     INTEGER DEFAULT 0,
    delivered_images INTEGER DEFAULT 0,
    notes            TEXT,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Photo galleries (delivery links)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photo_galleries (
    id               SERIAL PRIMARY KEY,
    shoot_id         INTEGER NOT NULL REFERENCES photo_shoots(id) ON DELETE CASCADE,
    name             VARCHAR(255) NOT NULL,
    url              TEXT,
    password         VARCHAR(100),
    expiry_date      DATE,
    is_public        BOOLEAN DEFAULT FALSE,
    download_enabled BOOLEAN DEFAULT TRUE,
    view_count       INTEGER DEFAULT 0,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Photo editing queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photo_editing_queue (
    id             SERIAL PRIMARY KEY,
    shoot_id       INTEGER NOT NULL REFERENCES photo_shoots(id) ON DELETE CASCADE,
    editor         VARCHAR(255),
    status         VARCHAR(20) DEFAULT 'pending'
                       CHECK (status IN (
                           'pending', 'in_progress', 'review', 'approved', 'delivered'
                       )),
    total_images   INTEGER,
    edited_images  INTEGER DEFAULT 0,
    style_preset   VARCHAR(100),
    due_date       DATE,
    notes          TEXT,
    created_at     TIMESTAMP DEFAULT NOW()
);
