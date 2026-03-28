-- Website templates table + seed data
-- Run against tenant schema (search_path must be set before executing)

CREATE TABLE IF NOT EXISTS website_templates (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    category        VARCHAR(100) NOT NULL,
    description     TEXT,
    thumbnail_url   VARCHAR(500),
    base_prompt     TEXT NOT NULL,
    base_html       TEXT NOT NULL,
    base_css        TEXT DEFAULT '',
    settings        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_templates_category ON website_templates(category);
CREATE INDEX IF NOT EXISTS idx_website_templates_slug ON website_templates(slug);

-- Seed industry templates
INSERT INTO website_templates (name, slug, category, description, base_prompt, base_html, base_css)
VALUES
(
    'Hair Salon & Spa',
    'salon-spa',
    'salon',
    'Elegant salon website with booking CTA, service menu, stylist profiles, and gallery.',
    'Create a modern, elegant hair salon and spa website. Use warm tones (rose gold, cream, soft pink). Include sections: hero with booking button, services menu with prices, stylist team profiles, photo gallery, contact with hours and map embed placeholder. Mobile-responsive. Professional typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Hair Salon & Spa</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#team">Our Team</a><a href="#gallery">Gallery</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-book">Book Appointment</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="team" class="team"><h2>Meet Our Stylists</h2><div class="team-grid"><!-- AI will populate --></div></section>
    <section id="gallery" class="gallery"><h2>Gallery</h2><div class="gallery-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Visit Us</h2><div class="contact-info"><!-- AI will populate --></div></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Segoe UI",sans-serif;color:#2d2d2d}.hero{background:linear-gradient(135deg,#f9e4e4,#fce4ec);text-align:center;padding:80px 20px}nav a{margin:0 15px;color:#8b6f6f;text-decoration:none}.btn-book{display:inline-block;margin-top:20px;padding:14px 32px;background:#c9917a;color:#fff;border-radius:30px;text-decoration:none}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#8b6f6f;margin-bottom:30px}.service-grid,.team-grid,.gallery-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#fce4ec;color:#8b6f6f}'
),
(
    'Construction & Trades',
    'construction',
    'construction',
    'Bold construction company site with project showcase, services, safety certifications, and quote request.',
    'Create a bold, professional construction company website. Use strong colors (navy blue, safety orange, concrete gray). Include sections: hero with "Get a Free Quote" CTA, services list (residential, commercial, renovation), featured projects gallery, safety certifications, testimonials, contact form. Mobile-responsive. Strong, masculine typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Construction Services</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#projects">Projects</a><a href="#about">About</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-quote">Get a Free Quote</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="projects" class="projects"><h2>Featured Projects</h2><div class="project-grid"><!-- AI will populate --></div></section>
    <section id="about" class="about"><h2>Why Choose Us</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Request a Quote</h2><form class="quote-form"><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Arial Black",sans-serif;color:#1a1a2e}.hero{background:linear-gradient(135deg,#1a1a2e,#16213e);text-align:center;padding:80px 20px;color:#fff}nav a{margin:0 15px;color:#e94560;text-decoration:none;font-weight:bold}.btn-quote{display:inline-block;margin-top:20px;padding:14px 32px;background:#e94560;color:#fff;border-radius:4px;text-decoration:none;font-weight:bold}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#1a1a2e;margin-bottom:30px}.service-grid,.project-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#1a1a2e;color:#e94560}'
),
(
    'Photography Portfolio',
    'photography',
    'photography',
    'Minimal, image-first photography portfolio with fullscreen gallery, about, and booking.',
    'Create a minimal, elegant photography portfolio website. Use dark/moody tones (charcoal, off-white, gold accent). Include sections: fullscreen hero image placeholder, portfolio gallery grid, about the photographer, services and pricing, contact/booking form. Mobile-responsive. Clean, minimal typography with generous whitespace.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Photography</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero"><h1>{{business_name}}</h1><p>{{tagline}}</p></header>
    <section id="portfolio" class="portfolio"><h2>Portfolio</h2><div class="photo-grid"><!-- AI will populate --></div></section>
    <section id="about" class="about"><h2>About</h2><!-- AI will populate --></section>
    <section id="pricing" class="pricing"><h2>Packages</h2><div class="pricing-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Book a Session</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Georgia",serif;color:#e0e0e0;background:#1a1a1a}.hero{height:80vh;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#111;color:#d4af37}h1{font-size:3rem;letter-spacing:4px}section{padding:60px 20px;max-width:1200px;margin:auto}h2{text-align:center;color:#d4af37;letter-spacing:2px}.photo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;color:#666}'
),
(
    'Restaurant & Cafe',
    'restaurant',
    'restaurant',
    'Warm restaurant site with menu, hours, reservation CTA, chef story, and location.',
    'Create a warm, inviting restaurant website. Use appetizing colors (burgundy, cream, olive green). Include sections: hero with reservation button, full menu with categories (appetizers, mains, desserts, drinks), chef story/about, hours and location with map placeholder, photo gallery. Mobile-responsive. Elegant serif typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Restaurant</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#menu">Menu</a><a href="#about">Our Story</a><a href="#hours">Hours</a><a href="#contact">Reserve</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-reserve">Make a Reservation</a>
    </header>
    <section id="menu" class="menu"><h2>Our Menu</h2><!-- AI will populate --></section>
    <section id="about" class="about"><h2>Our Story</h2><!-- AI will populate --></section>
    <section id="hours" class="hours"><h2>Hours & Location</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Reservations</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Playfair Display",Georgia,serif;color:#2d1f1f;background:#faf5f0}.hero{background:linear-gradient(135deg,#3d1f1f,#5a2d2d);text-align:center;padding:80px 20px;color:#faf5f0}nav a{margin:0 15px;color:#c9a96e;text-decoration:none}.btn-reserve{display:inline-block;margin-top:20px;padding:14px 32px;background:#c9a96e;color:#2d1f1f;border-radius:4px;text-decoration:none;font-weight:bold}section{padding:60px 20px;max-width:1000px;margin:auto}h2{text-align:center;color:#5a2d2d;margin-bottom:30px}footer{text-align:center;padding:30px;background:#3d1f1f;color:#c9a96e}'
),
(
    'Fitness & Gym',
    'fitness',
    'fitness',
    'High-energy gym website with class schedule, trainer profiles, membership plans, and signup CTA.',
    'Create a high-energy fitness and gym website. Use bold colors (electric blue, neon green, dark charcoal). Include sections: hero with "Join Now" CTA, class schedule grid, trainer profiles, membership pricing tiers (basic/pro/elite), testimonials, contact and location. Mobile-responsive. Bold, sporty typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Fitness</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#classes">Classes</a><a href="#trainers">Trainers</a><a href="#pricing">Pricing</a><a href="#contact">Join</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#pricing" class="btn-join">Join Now</a>
    </header>
    <section id="classes" class="classes"><h2>Class Schedule</h2><div class="schedule-grid"><!-- AI will populate --></div></section>
    <section id="trainers" class="trainers"><h2>Our Trainers</h2><div class="trainer-grid"><!-- AI will populate --></div></section>
    <section id="pricing" class="pricing"><h2>Membership Plans</h2><div class="pricing-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Get Started</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Impact",sans-serif;color:#e0e0e0;background:#1a1a2e}.hero{background:linear-gradient(135deg,#0f0f23,#1a1a2e);text-align:center;padding:80px 20px;color:#00f5d4}nav a{margin:0 15px;color:#00bbf9;text-decoration:none;text-transform:uppercase}.btn-join{display:inline-block;margin-top:20px;padding:14px 32px;background:#00f5d4;color:#0f0f23;border-radius:4px;text-decoration:none;font-weight:bold;text-transform:uppercase}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#00f5d4;text-transform:uppercase;letter-spacing:3px}.schedule-grid,.trainer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px}.pricing-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}footer{text-align:center;padding:30px;background:#0f0f23;color:#00bbf9}'
),
(
    'Professional Services',
    'professional',
    'professional',
    'Clean professional services site for consultants, lawyers, accountants with service pages and contact.',
    'Create a clean, trustworthy professional services website suitable for consultants, lawyers, or accountants. Use corporate colors (navy, white, steel blue accent). Include sections: hero with consultation CTA, services overview, team/partner profiles, client testimonials, case studies preview, contact form with office location. Mobile-responsive. Professional sans-serif typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Professional Services</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#team">Team</a><a href="#testimonials">Clients</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-consult">Schedule Consultation</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="team" class="team"><h2>Our Team</h2><div class="team-grid"><!-- AI will populate --></div></section>
    <section id="testimonials" class="testimonials"><h2>Client Testimonials</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Contact Us</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Segoe UI",Helvetica,sans-serif;color:#2c3e50;background:#fff}.hero{background:linear-gradient(135deg,#1a365d,#2d4a7a);text-align:center;padding:80px 20px;color:#fff}nav a{margin:0 15px;color:#90cdf4;text-decoration:none}.btn-consult{display:inline-block;margin-top:20px;padding:14px 32px;background:#4299e1;color:#fff;border-radius:4px;text-decoration:none}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#1a365d;margin-bottom:30px}.service-grid,.team-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#1a365d;color:#90cdf4}'
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    base_prompt = EXCLUDED.base_prompt,
    base_html = EXCLUDED.base_html,
    base_css = EXCLUDED.base_css;
