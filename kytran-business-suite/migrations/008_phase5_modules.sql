INSERT INTO module_catalog (slug, name, description, category, tier_required, icon) VALUES
    ('industry', 'Industry Framework', 'Core job management, permits, and government opportunities for all trades', 'ecommerce', 'business', 'briefcase'),
    ('industry-construction', 'Construction', 'Project management, subcontractors, RFIs, change orders, inspections', 'ecommerce', 'business', 'hard-hat'),
    ('industry-electrical', 'Electrical', 'Panel design, circuits, load calculations, materials tracking', 'ecommerce', 'business', 'zap'),
    ('industry-plumbing', 'Plumbing', 'Service calls, fixtures, parts inventory, backflow testing', 'ecommerce', 'business', 'droplet'),
    ('industry-mechanical', 'Mechanical/HVAC', 'HVAC systems, maintenance schedules, energy audits, commissioning', 'ecommerce', 'business', 'thermometer'),
    ('industry-salon', 'Salon & Hairdressing', 'Services, stylists, bookings, product inventory, client history', 'ecommerce', 'business', 'scissors'),
    ('industry-photography', 'Photography', 'Shoots, packages, galleries, editing queue', 'ecommerce', 'business', 'camera'),
    ('industry-limo', 'Limo Service', 'Fleet management, drivers, dispatch, bookings, maintenance', 'ecommerce', 'business', 'car')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;
