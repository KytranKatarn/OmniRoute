-- Website Builder migration 004 — seed ARCHIE application templates.
-- These complement the existing industry templates from migration 002.
-- All statements are idempotent (ON CONFLICT DO NOTHING on slug).

INSERT INTO website_templates (name, slug, category, description, base_prompt, base_html, base_css, settings)
VALUES
(
    'SaaS Landing Page',
    'saas-landing',
    'application',
    'Modern SaaS product landing page with hero, features, pricing, and CTA sections',
    'Create a modern SaaS landing page with a bold hero section, feature highlights with icons, a pricing table with 3 tiers, customer testimonials, and a strong call-to-action. Use a dark theme with accent colors.',
    '<div class="hero"><h1>Your Product Name</h1><p>The modern solution for modern teams</p><button class="btn">Get Started Free</button></div><section class="features"><h2>Features</h2></section><section class="pricing"><h2>Pricing</h2></section>',
    ':root { --primary: #6366f1; --bg: #0f172a; } body { background: var(--bg); color: #e2e8f0; font-family: Inter, sans-serif; }',
    '{"industry": "technology", "type": "landing"}'::jsonb
),
(
    'Agency Portfolio',
    'agency',
    'application',
    'Creative agency portfolio showcasing work, team, and services',
    'Create a creative agency website with a dramatic hero, portfolio grid with hover effects, team section with photos, services overview, and contact form. Bold typography with subtle animations.',
    '<div class="hero"><h1>We Create Digital Experiences</h1></div><section class="portfolio"><h2>Our Work</h2></section><section class="team"><h2>Meet the Team</h2></section>',
    ':root { --primary: #e94560; --bg: #1a1a2e; } body { background: var(--bg); color: #eee; font-family: Montserrat, sans-serif; }',
    '{"industry": "creative", "type": "portfolio"}'::jsonb
),
(
    'Startup MVP',
    'startup',
    'application',
    'Clean startup landing page focused on early user acquisition',
    'Create a minimal startup landing page with a clear value proposition hero, problem/solution section, early access signup form, and social proof. Focus on conversion.',
    '<div class="hero"><h1>Solve [Problem] in Minutes</h1><p>Join 1,000+ early adopters</p><form class="signup"><input type="email" placeholder="your@email.com"><button>Get Early Access</button></form></div>',
    ':root { --primary: #10b981; --bg: #fafafa; } body { background: var(--bg); color: #1a1a1a; font-family: system-ui, sans-serif; }',
    '{"industry": "startup", "type": "landing"}'::jsonb
),
(
    'Corporate',
    'corporate',
    'application',
    'Professional corporate website with sections for services, leadership, and contact',
    'Create a professional corporate website with executive hero, services grid, leadership team section, company values, and contact information. Conservative color scheme with trust-building elements.',
    '<div class="hero"><h1>Enterprise Solutions</h1><p>Trusted by Fortune 500 companies</p></div><section class="services"><h2>Our Services</h2></section>',
    ':root { --primary: #1e40af; --bg: #ffffff; } body { background: var(--bg); color: #1e293b; font-family: Georgia, serif; }',
    '{"industry": "enterprise", "type": "corporate"}'::jsonb
),
(
    'E-Commerce Storefront',
    'storefront',
    'application',
    'Online store template with product grid, cart, and checkout flow',
    'Create an e-commerce storefront with featured products hero, product category grid, individual product cards with prices, shopping cart sidebar, and newsletter signup. Warm, inviting colors.',
    '<div class="hero"><h1>Shop Our Collection</h1></div><section class="products"><h2>Featured Products</h2></section><section class="categories"><h2>Shop by Category</h2></section>',
    ':root { --primary: #f59e0b; --bg: #fffbeb; } body { background: var(--bg); color: #1c1917; font-family: Nunito, sans-serif; }',
    '{"industry": "retail", "type": "ecommerce"}'::jsonb
),
(
    'Product Showcase',
    'product-showcase',
    'application',
    'Single product landing page with features, specs, and purchase CTA',
    'Create a product showcase page with full-width product hero image, key features with icons, technical specifications table, customer reviews, and buy/pre-order button. Apple-style minimal design.',
    '<div class="hero"><h1>Product Name</h1><p>Reimagined. Refined. Revolutionary.</p></div><section class="features"><h2>Key Features</h2></section>',
    ':root { --primary: #3b82f6; --bg: #000000; } body { background: var(--bg); color: #f8fafc; font-family: SF Pro Display, system-ui, sans-serif; }',
    '{"industry": "product", "type": "showcase"}'::jsonb
),
(
    'Dashboard UI',
    'dashboard',
    'application',
    'Admin dashboard layout with sidebar, stats cards, and data tables',
    'Create a dashboard UI with sidebar navigation, top stats cards, recent activity feed, data table with sorting, and quick action buttons. Dark theme with cyan accents.',
    '<div class="dashboard"><aside class="sidebar"><nav></nav></aside><main class="content"><h1>Dashboard</h1><div class="stats-grid"></div></main></div>',
    ':root { --primary: #06b6d4; --bg: #0f172a; --sidebar: #1e293b; } body { background: var(--bg); color: #e2e8f0; font-family: JetBrains Mono, monospace; }',
    '{"industry": "technology", "type": "dashboard"}'::jsonb
),
(
    'Portfolio',
    'portfolio',
    'application',
    'Personal portfolio for developers, designers, or creatives',
    'Create a personal portfolio with animated hero introduction, project showcase with filtering, skills/tech stack section, blog preview, and contact form. Creative, personality-driven design.',
    '<div class="hero"><h1>Hi, I am [Name]</h1><p>Developer & Designer</p></div><section class="projects"><h2>Selected Work</h2></section><section class="skills"><h2>Skills</h2></section>',
    ':root { --primary: #8b5cf6; --bg: #0c0a1d; } body { background: var(--bg); color: #d4d4d8; font-family: Space Grotesk, sans-serif; }',
    '{"industry": "personal", "type": "portfolio"}'::jsonb
)
ON CONFLICT (slug) DO NOTHING;
