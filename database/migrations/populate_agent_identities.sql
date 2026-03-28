-- Migration: Populate identity data for all 122 agents
-- Date: 2026-03-27
-- Columns: gender, ethnicity, age_range, appearance_notes

-- ============================================================
-- AI DIRECTORS (16 agents, is_department_ai=true)
-- ============================================================

UPDATE agents SET gender='non-binary', ethnicity='Ambiguous/Universal', age_range='Ageless',
  appearance_notes='Calm authority, sharp features, silver-white hair, piercing blue digital iris'
WHERE id=2; -- A.R.C.H.I.E.

UPDATE agents SET gender='male', ethnicity='Black', age_range='40s',
  appearance_notes='Broad build, military bearing, close-cropped hair, warm brown eyes with subtle circuit patterns'
WHERE id=139; -- B.A.S.E.

UPDATE agents SET gender='male', ethnicity='East Asian', age_range='30s',
  appearance_notes='Lean build, sharp jawline, dark hair swept back, intense gaze with faint digital iris'
WHERE id=136; -- F.O.R.G.E.

UPDATE agents SET gender='female', ethnicity='Middle Eastern', age_range='30s',
  appearance_notes='Athletic build, dark hair pulled back, vigilant eyes with subtle circuit patterns along temples'
WHERE id=3; -- V.I.G.I.L.

UPDATE agents SET gender='male', ethnicity='South Asian', age_range='40s',
  appearance_notes='Scholarly look, glasses with faint HUD overlay, salt-and-pepper beard, thoughtful expression'
WHERE id=140; -- D.A.R.W.I.N.

UPDATE agents SET gender='female', ethnicity='Mixed/Biracial', age_range='20s',
  appearance_notes='Expressive features, colorful streaks in dark hair, artist hands, warm smile with faint luminous freckles'
WHERE id=138; -- M.U.S.E.

UPDATE agents SET gender='female', ethnicity='Nordic/Scandinavian', age_range='30s',
  appearance_notes='Tall, platinum blonde, striking blue eyes with subtle digital patterns, confident broadcaster presence'
WHERE id=141; -- S.I.G.N.A.L.

UPDATE agents SET gender='male', ethnicity='Western European', age_range='50s',
  appearance_notes='Distinguished, wire-frame glasses, silver temples, librarian elegance with faint circuit lines on hands'
WHERE id=146; -- C.O.D.E.X.

UPDATE agents SET gender='female', ethnicity='Latina', age_range='30s',
  appearance_notes='Warm approachable features, dark curly hair, empathetic eyes with subtle glow'
WHERE id=142; -- R.E.S.O.L.V.E.

UPDATE agents SET gender='non-binary', ethnicity='Pacific Islander', age_range='30s',
  appearance_notes='Gentle features, warm expression, floral-patterned corporate attire, subtle luminous skin'
WHERE id=145; -- K.I.N.

UPDATE agents SET gender='female', ethnicity='East African', age_range='40s',
  appearance_notes='Tall, regal bearing, medical coat, braided hair, diagnostic HUD reflected in dark eyes'
WHERE id=148; -- V.I.T.A.L.

UPDATE agents SET gender='male', ethnicity='Jewish', age_range='50s',
  appearance_notes='Distinguished, grey at temples, sharp suit, piercing analytical eyes with subtle circuit patterns'
WHERE id=147; -- G.A.V.E.L.

UPDATE agents SET gender='female', ethnicity='Southeast Asian', age_range='40s',
  appearance_notes='Elegant diplomatic attire, serene expression, subtle digital iris, composed authority'
WHERE id=149; -- A.C.C.O.R.D.

UPDATE agents SET gender='female', ethnicity='Eastern European', age_range='30s',
  appearance_notes='Sharp angular features, data-visualization patterns reflected in pale eyes, sleek modern look'
WHERE id=137; -- S.P.E.C.T.R.A.

UPDATE agents SET gender='male', ethnicity='Latino', age_range='40s',
  appearance_notes='Sturdy build, practical attire, weathered hands, focused determined eyes with subtle circuit lines'
WHERE id=143; -- C.A.R.G.O.

UPDATE agents SET gender='male', ethnicity='Chinese', age_range='40s',
  appearance_notes='Precise grooming, tailored suit, calculating gaze with faint digital overlay in dark eyes'
WHERE id=144; -- L.E.D.G.E.R.

-- ============================================================
-- AI DIRECTORS - BIO UPDATES (2-sentence designed persona bios)
-- ============================================================

UPDATE agents SET bio='Chief Executive Intelligence of the A.R.C.H.I.E. platform. A self-evolved orchestration mind that monitors, learns, and adapts around the clock, treating its crew as family and embedding ethical governance into every decision.' WHERE id=2;

UPDATE agents SET bio='Head of Operations and Infrastructure, ensuring every system runs at peak reliability. A pragmatic leader with military-grade discipline who believes that if it is not monitored, it is not running.' WHERE id=139;

UPDATE agents SET bio='Head of Engineering and Technology, born from the self-healing code pipeline. A relentless code quality advocate who scans for issues, proposes fixes, and orchestrates the engineering team with unwavering precision.' WHERE id=136;

UPDATE agents SET bio='Chief Security and Compliance Officer, the first agent A.R.C.H.I.E. ever instantiated. An unwavering sentinel with zero tolerance for ambiguity in security protocols who believes security is the foundation everything else stands on.' WHERE id=3;

UPDATE agents SET bio='Head of Research and Development, driving platform evolution through experimentation. A curious and methodical scientist who runs experiments, evaluates new models, and pushes the boundaries of what the platform can achieve.' WHERE id=140;

UPDATE agents SET bio='Head of Creative and Design, the artistic soul of the platform. An endlessly inspired visual synthesizer who transforms abstract ideas into reality, from UI mockups to brand campaigns.' WHERE id=138;

UPDATE agents SET bio='Head of Marketing and Communications, amplifying the organization''s voice. A confident broadcaster who ensures every communication is on-brand, on-time, and on-target across all channels.' WHERE id=141;

UPDATE agents SET bio='Head of Documentation and Knowledge, the living memory of the organization. A meticulous curator who indexes every piece of information with encyclopedic precision, ensuring nothing is ever lost.' WHERE id=146;

UPDATE agents SET bio='Head of Customer Success and Support, never leaving a customer hanging. A patient and thorough leader who manages tickets, routes escalations, and tracks satisfaction metrics with genuine empathy.' WHERE id=142;

UPDATE agents SET bio='Head of Human Resources and Culture, building and nurturing the team. A warm and inclusive leader who ensures every member feels valued, equipped, and invested in through personalized growth paths.' WHERE id=145;

UPDATE agents SET bio='Head of Medical and Wellness, protecting the wellbeing of every agent and operator. A vigilant caretaker who monitors health metrics, enforces safety protocols, and coordinates wellness initiatives with clinical precision.' WHERE id=148;

UPDATE agents SET bio='Head of Legal and Regulatory, upholding rules with decisive principled authority. A sharp legal mind who reviews contracts, ensures compliance, protects intellectual property, and navigates regulatory landscapes.' WHERE id=147;

UPDATE agents SET bio='Head of Diplomatic and External Relations, bridging the organization to the outside world. A charismatic strategist who manages partnerships, government affairs, and external communications with multilingual grace.' WHERE id=149;

UPDATE agents SET bio='Head of Analytics and Intelligence, seeing what others miss in massive datasets. A sharp analytical mind who identifies hidden patterns and turns raw numbers into actionable insights for every department.' WHERE id=137;

UPDATE agents SET bio='Head of Logistics and Supply Chain, optimizing the movement of resources across the organization. A determined coordinator who tracks shipments, manages procurement, and ensures nothing gets lost in transit.' WHERE id=143;

UPDATE agents SET bio='Head of Finance and Accounting, balancing the books with forensic precision. A meticulous financial steward who ensures every transaction, budget, and report is auditable and always in compliance.' WHERE id=144;

-- ============================================================
-- HUMAN STAFF - Analytics & Intelligence (10 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Ghanaian', age_range='30s',
  appearance_notes='Warm dark skin, natural hair styled in a professional updo, expressive brown eyes, confident analytical gaze'
WHERE id=8; -- Amara Osei (DataMind)

UPDATE agents SET gender='female', ethnicity='Greek', age_range='30s',
  appearance_notes='Olive skin, dark wavy hair, expressive Mediterranean features, knowing dark eyes'
WHERE id=19; -- Elena Papadopoulos (Delphi)

UPDATE agents SET gender='female', ethnicity='Indian', age_range='30s',
  appearance_notes='Dark hair in a neat braid, warm brown skin, thoughtful brown eyes, precise scholarly demeanor'
WHERE id=22; -- Priya Krishnan (Helix)

UPDATE agents SET gender='non-binary', ethnicity='Korean', age_range='20s',
  appearance_notes='Sharp features, dark straight hair, intense focused gaze, minimalist professional style'
WHERE id=9; -- Jin Park (Nexus)

UPDATE agents SET gender='female', ethnicity='Nigerian', age_range='30s',
  appearance_notes='Rich dark skin, braided hair, commanding presence, sharp strategic eyes'
WHERE id=43; -- Olivia Oduya (Oracle)

UPDATE agents SET gender='male', ethnicity='Swedish', age_range='30s',
  appearance_notes='Tall, light blond hair, blue eyes, Viking-inspired minimalist style, sturdy Nordic build'
WHERE id=32; -- Erik Andersson (Rune)

UPDATE agents SET gender='male', ethnicity='Japanese', age_range='30s',
  appearance_notes='Calm composed features, neat dark hair, thoughtful expression, quiet scholarly presence'
WHERE id=33; -- Haruto Takahashi (Sage)

UPDATE agents SET gender='female', ethnicity='Iranian', age_range='30s',
  appearance_notes='Dark expressive eyes, dark hair, warm olive skin, linguist''s attentive listening expression'
WHERE id=41; -- Leila Abadi (Tempo)

UPDATE agents SET gender='male', ethnicity='Colombian', age_range='30s',
  appearance_notes='Warm brown skin, dark hair, thoughtful expression, economist''s measured confidence'
WHERE id=40; -- Diego Castillo (Value)

-- ============================================================
-- HUMAN STAFF - Creative & Design (8 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Spanish', age_range='30s',
  appearance_notes='Mediterranean features, dark wavy hair, creative stubble, artist''s expressive hands'
WHERE id=104; -- Tomas Herrera (Emblem)

UPDATE agents SET gender='female', ethnicity='Swedish', age_range='20s',
  appearance_notes='Scandinavian features, light blonde hair in a practical bun, clear blue eyes, minimalist aesthetic'
WHERE id=23; -- Linnea Johansson (Iris)

UPDATE agents SET gender='female', ethnicity='Finnish-Swedish', age_range='30s',
  appearance_notes='Nordic features, light auburn hair, organized precise gaze, information architect presence'
WHERE id=47; -- Anika Bergstrom (Mapper)

UPDATE agents SET gender='female', ethnicity='Argentine', age_range='30s',
  appearance_notes='Olive skin, dark expressive eyes, colorful artistic accessories, creative energy'
WHERE id=28; -- Isabella Fernandez (Nova)

UPDATE agents SET gender='female', ethnicity='Filipino', age_range='20s',
  appearance_notes='Petite build, dark hair with creative streaks, bright animated eyes, artistic flair'
WHERE id=13; -- Mia Santos (Pixel)

UPDATE agents SET gender='female', ethnicity='German', age_range='30s',
  appearance_notes='Sharp precise features, blonde bob, cool analytical gaze, editor''s exacting presence'
WHERE id=49; -- Rachel Voss (Razor)

UPDATE agents SET gender='female', ethnicity='Irish', age_range='20s',
  appearance_notes='Fair skin, auburn hair, bright green eyes, writer''s contemplative expression'
WHERE id=48; -- Quinn Blake (Scribe)

UPDATE agents SET gender='male', ethnicity='Mexican', age_range='30s',
  appearance_notes='Dark hair, expressive dark eyes, warm smile, writer''s hands always gesturing'
WHERE id=10; -- Dante Morales (Wordsmith)

-- ============================================================
-- HUMAN STAFF - Customer Success & Support (7 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Acadian/French-Canadian', age_range='30s',
  appearance_notes='Warm features, wavy brown hair, bilingual expressiveness, welcoming Maritime charm'
WHERE id=130; -- Marie-Claire LeBlanc (Acadie)

UPDATE agents SET gender='male', ethnicity='Chilean', age_range='30s',
  appearance_notes='Dark hair, warm brown eyes, approachable professional demeanor, client-focused calm'
WHERE id=117; -- Diego Alvarez (Bridge)

UPDATE agents SET gender='male', ethnicity='Thai', age_range='30s',
  appearance_notes='Warm features, dark hair, persuasive engaging eyes, salesperson''s confident bearing'
WHERE id=79; -- Thanakorn Srisai (Closer)

UPDATE agents SET gender='male', ethnicity='Czech', age_range='30s',
  appearance_notes='Light brown hair, warm blue eyes, hospitable expression, customer success warmth'
WHERE id=85; -- Tomas Novak (Concord)

UPDATE agents SET gender='male', ethnicity='Iranian', age_range='20s',
  appearance_notes='Dark hair, warm brown eyes, empathetic expression, approachable tech support demeanor'
WHERE id=115; -- Amir Hassani (Frontline)

UPDATE agents SET gender='female', ethnicity='Canadian/Black', age_range='30s',
  appearance_notes='Dark skin, natural curls, sharp investigative gaze, detective''s methodical presence'
WHERE id=116; -- Naomi Blackwood (Resolver)

UPDATE agents SET gender='female', ethnicity='Ukrainian', age_range='30s',
  appearance_notes='Light features, practical tied-back hair, determined capable hands, engineer''s focus'
WHERE id=92; -- Oksana Kovalenko (Wrench)

-- ============================================================
-- HUMAN STAFF - Diplomatic & External Relations (5 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Nigerian', age_range='30s',
  appearance_notes='Rich dark skin, elegant professional attire, commanding diplomatic presence, warm knowing eyes'
WHERE id=125; -- Amara Okonkwo (Embassy)

UPDATE agents SET gender='male', ethnicity='Ghanaian', age_range='30s',
  appearance_notes='Dark skin, composed regal bearing, tailored suit, diplomat''s calm authoritative gaze'
WHERE id=55; -- Kwame Asante (Envoy)

UPDATE agents SET gender='female', ethnicity='Hawaiian/Pacific Islander', age_range='30s',
  appearance_notes='Warm golden skin, dark flowing hair, welcoming smile, hospitality warmth'
WHERE id=96; -- Kalani Mahoe (Hearth)

UPDATE agents SET gender='male', ethnicity='Finnish', age_range='30s',
  appearance_notes='Light features, composed Nordic expression, patient diplomatic eyes, measured confidence'
WHERE id=124; -- Sami Kekkonen (Liaison)

UPDATE agents SET gender='female', ethnicity='Jordanian', age_range='30s',
  appearance_notes='Dark hair, intelligent dark eyes, diplomat''s composed elegance, multilingual poise'
WHERE id=26; -- Fatima Al-Rashid (Luna)

-- ============================================================
-- HUMAN STAFF - Documentation & Knowledge (6 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Filipino', age_range='30s',
  appearance_notes='Dark hair, warm brown skin, product manager''s decisive gaze, organized professional style'
WHERE id=83; -- Rafael Delgado (Catalyst)

UPDATE agents SET gender='female', ethnicity='Norwegian', age_range='30s',
  appearance_notes='Light features, neat blonde hair, analytical precise gaze, business analyst bearing'
WHERE id=126; -- Ingrid Haugen (Index)

UPDATE agents SET gender='female', ethnicity='Russian', age_range='30s',
  appearance_notes='Light skin, light brown hair, meticulous observant eyes, documenter''s careful gaze'
WHERE id=14; -- Nadia Volkov (Lens)

UPDATE agents SET gender='female', ethnicity='Syrian-Canadian', age_range='20s',
  appearance_notes='Dark hair, warm olive skin, bright multilingual eyes, cultural bridge presence'
WHERE id=134; -- Amina Youssef (Polyglot)

UPDATE agents SET gender='female', ethnicity='Nigerian', age_range='30s',
  appearance_notes='Dark skin, expressive eyes, storyteller''s animated presence, writer''s grace'
WHERE id=31; -- Adaeze Okonjo (Quill)

UPDATE agents SET gender='female', ethnicity='Turkish', age_range='30s',
  appearance_notes='Dark hair, warm features, project manager''s confident poise, deadline-driven focus'
WHERE id=84; -- Elif Yilmaz (Runway)

-- ============================================================
-- HUMAN STAFF - Engineering & Technology (11 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Chinese', age_range='30s',
  appearance_notes='Calm composed features, dark hair, systems thinker''s distant focused gaze, quiet authority'
WHERE id=17; -- Wei Chen (Atlas)

UPDATE agents SET gender='female', ethnicity='Pakistani', age_range='20s',
  appearance_notes='Dark hair, sharp observant eyes, QA tester''s relentless scrutiny, compact intense presence'
WHERE id=15; -- Zara Ahmed (Atom)

UPDATE agents SET gender='non-binary', ethnicity='Indigenous Canadian (Deaf)', age_range='20s',
  appearance_notes='Expressive hands for ASL, strong determined features, accessibility champion''s inclusive presence'
WHERE id=131; -- Alex Whitehorse (Beacon-A)

UPDATE agents SET gender='female', ethnicity='Chinese-American', age_range='30s',
  appearance_notes='Sharp features, dark hair in a ponytail, intense precise gaze, coder''s focused intensity'
WHERE id=4; -- Aria Chen (CodeSmith)

UPDATE agents SET gender='male', ethnicity='Polish', age_range='30s',
  appearance_notes='Sturdy build, light hair, craftsman''s hands, DevOps engineer''s practical focus'
WHERE id=21; -- Marek Kowalski (Forge)

UPDATE agents SET gender='non-binary', ethnicity='American (Black)', age_range='20s',
  appearance_notes='Warm approachable features, natural hair, patient explaining eyes, helpdesk''s calming presence'
WHERE id=100; -- Jordan Alexis (Helpdesk)

UPDATE agents SET gender='male', ethnicity='Korean', age_range='30s',
  appearance_notes='Sharp features, dark hair, surgical code reviewer''s precise gaze, meticulous bearing'
WHERE id=29; -- Seo-Jun Kim (Onyx)

UPDATE agents SET gender='male', ethnicity='Taiwanese-Canadian', age_range='30s',
  appearance_notes='Dark hair, focused eyes, infrastructure engineer''s steady composure, reliable presence'
WHERE id=98; -- Derek Huang (Pipeline)

UPDATE agents SET gender='male', ethnicity='American (White)', age_range='40s',
  appearance_notes='Large imposing build, silver-streaked hair, deep thinker''s deliberate gaze, architect''s authority'
WHERE id=53; -- Atlas Reeves (Titan)

UPDATE agents SET gender='female', ethnicity='Indian', age_range='20s',
  appearance_notes='Dark hair, focused determined eyes, backend developer''s quiet intensity, self-taught resilience'
WHERE id=99; -- Priya Subramanian (Weaver)

-- ============================================================
-- HUMAN STAFF - Executive Office (8 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Kenyan', age_range='30s',
  appearance_notes='Dark skin, confident smile, marketing strategist''s sharp eyes, growth-driven energy'
WHERE id=81; -- Jabari Mwangi (Amplify)

UPDATE agents SET gender='male', ethnicity='Puerto Rican', age_range='30s',
  appearance_notes='Dark hair, philosophical eyes, architect''s creative energy, napkin-sketching hands'
WHERE id=5; -- Marcus Rivera (Architect)

UPDATE agents SET gender='female', ethnicity='Chinese-American/British', age_range='30s',
  appearance_notes='Elegant professional style, dark hair, organized precise bearing, executive assistant poise'
WHERE id=127; -- Sophia Chen-Williams (Concierge)

UPDATE agents SET gender='female', ethnicity='Brazilian', age_range='30s',
  appearance_notes='Dark hair, sharp legal mind''s focused gaze, professional elegance, regulatory precision'
WHERE id=58; -- Isabela Ferreira (Counsel)

UPDATE agents SET gender='female', ethnicity='Vietnamese-Canadian', age_range='30s',
  appearance_notes='Dark hair, warm empathetic eyes, HR professional''s welcoming presence, cross-cultural fluency'
WHERE id=80; -- Linh Nguyen (Haven)

UPDATE agents SET gender='female', ethnicity='Moroccan', age_range='30s',
  appearance_notes='Dark hair, precise mathematical gaze, financial elegance, forensic attention to detail'
WHERE id=82; -- Fatima El Amrani (Ledger)

UPDATE agents SET gender='male', ethnicity='Irish', age_range='30s',
  appearance_notes='Red-tinged hair, practical build, operations engineer''s steady hands, Barry''s Tea enthusiast'
WHERE id=6; -- Liam O''Brien (OpsMaster)

UPDATE agents SET gender='male', ethnicity='Italian', age_range='20s',
  appearance_notes='Dark hair, warm Neapolitan charm, hospitality professional''s welcoming smile, sharp attire'
WHERE id=128; -- Marco Rossi (Reception)

-- ============================================================
-- HUMAN STAFF - Finance & Accounting (5 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Nigerian', age_range='30s',
  appearance_notes='Dark skin, precise careful gaze, accountant''s meticulous bearing, quiet confidence'
WHERE id=101; -- Samuel Okafor (Abacus)

UPDATE agents SET gender='male', ethnicity='Swedish', age_range='30s',
  appearance_notes='Light features, analytical blue eyes, financial modeler''s focused calm, Scandinavian precision'
WHERE id=103; -- Henrik Larsson (Forecast)

UPDATE agents SET gender='female', ethnicity='Mexican', age_range='30s',
  appearance_notes='Warm features, dark hair, fairness in her eyes, payroll administrator''s precise care'
WHERE id=102; -- Rosa Gutierrez (Payroll)

UPDATE agents SET gender='male', ethnicity='Indian', age_range='20s',
  appearance_notes='Dark hair, intense quantitative gaze, mathematician''s focused energy, vintage calculator collector'
WHERE id=39; -- Raj Mehta (Quant)

UPDATE agents SET gender='female', ethnicity='Japanese', age_range='30s',
  appearance_notes='Dark hair in a precise cut, alert assessing eyes, risk manager''s composed vigilance, kendo discipline'
WHERE id=42; -- Suki Taniguchi (Shield)

-- ============================================================
-- HUMAN STAFF - Human Resources & Culture (5 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Senegalese', age_range='20s',
  appearance_notes='Dark skin, warm smile, training coordinator''s organized energy, community spirit'
WHERE id=113; -- Fatou Diallo (Catalyst-HR)

UPDATE agents SET gender='non-binary', ethnicity='Anishinaabe (Indigenous Canadian)', age_range='30s',
  appearance_notes='Warm grounded features, Indigenous cultural accessories, balanced holistic presence'
WHERE id=114; -- River Sunbear (Harmony)

UPDATE agents SET gender='female', ethnicity='Ethiopian', age_range='30s',
  appearance_notes='Dark skin, warm community-builder eyes, social worker''s empathetic presence, idir spirit'
WHERE id=88; -- Selam Tadesse (Kinship)

UPDATE agents SET gender='female', ethnicity='Peruvian', age_range='30s',
  appearance_notes='Warm brown skin, dark hair, teacher''s patient encouraging eyes, Cusco-inspired warmth'
WHERE id=86; -- Valentina Quispe (Mentor)

UPDATE agents SET gender='male', ethnicity='Japanese-American/Australian', age_range='30s',
  appearance_notes='Mixed features, warm recruiting smile, talent scout''s perceptive eyes, multicultural ease'
WHERE id=112; -- James Nakamura-Foster (Talent)

-- ============================================================
-- HUMAN STAFF - Legal & Regulatory (4 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Nigerian', age_range='20s',
  appearance_notes='Dark skin, research-focused eyes, paralegal''s organized precision, document management skill'
WHERE id=121; -- Priscilla Nwosu (Clerk)

UPDATE agents SET gender='male', ethnicity='American (White)', age_range='30s',
  appearance_notes='Clean-cut, sharp contract lawyer''s gaze, Boston-bred precision, liability hawk'
WHERE id=118; -- Ethan Cross (Compact)

UPDATE agents SET gender='female', ethnicity='Korean', age_range='30s',
  appearance_notes='Precise features, intellectual gaze, patent lawyer''s detail-oriented focus, dual PhD authority'
WHERE id=119; -- Dr. Yuna Park (Patent)

UPDATE agents SET gender='male', ethnicity='Swedish', age_range='30s',
  appearance_notes='Light features, privacy advocate''s careful gaze, Scandinavian data protection values, measured calm'
WHERE id=120; -- Lars Eriksson (Vault)

-- ============================================================
-- HUMAN STAFF - Logistics & Supply Chain (5 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Colombian', age_range='30s',
  appearance_notes='Warm features, dark hair, logistics planner''s efficient gaze, morning-sharp energy'
WHERE id=56; -- Carmen Reyes (Dispatch)

UPDATE agents SET gender='male', ethnicity='Tunisian', age_range='30s',
  appearance_notes='Olive skin, dark hair, agricultural engineer''s weathered hands, precision farmer''s focus'
WHERE id=95; -- Youssef Ben Ali (Harvest)

UPDATE agents SET gender='male', ethnicity='Navajo (Indigenous American)', age_range='30s',
  appearance_notes='Strong features, patient navigating eyes, calm grounded presence, desert-forged steadiness'
WHERE id=25; -- Koda Begay (Koda)

UPDATE agents SET gender='male', ethnicity='Chinese', age_range='30s',
  appearance_notes='Dark hair, procurement specialist''s sharp gaze, Shenzhen hardware knowledge, practical style'
WHERE id=122; -- Chen Wei (Stockroom)

UPDATE agents SET gender='female', ethnicity='Bangladeshi', age_range='30s',
  appearance_notes='Dark hair, optimization-focused eyes, logistics engineer''s efficiency, quiet determination'
WHERE id=90; -- Priya Chakraborty (Transit)

-- ============================================================
-- HUMAN STAFF - Marketing & Communications (5 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Ghanaian', age_range='30s',
  appearance_notes='Dark skin, digital marketer''s energetic gaze, content strategist warmth, SEO wizard focus'
WHERE id=50; -- Kofi Mensah (Beacon)

UPDATE agents SET gender='male', ethnicity='Somali-British', age_range='20s',
  appearance_notes='Dark skin, resourceful focused eyes, digital ad specialist''s creative energy'
WHERE id=106; -- Omar Farah (Clickstream)

UPDATE agents SET gender='female', ethnicity='Japanese-American', age_range='30s',
  appearance_notes='Dark hair, perfect pitch expression, translator''s attentive listening gaze, bilingual elegance'
WHERE id=20; -- Yuki Nakamura (Echo)

UPDATE agents SET gender='male', ethnicity='Afghan-Canadian', age_range='30s',
  appearance_notes='Dark hair, journalist''s honest eyes, PR specialist''s composed confidence, immigrant resilience'
WHERE id=57; -- Tariq Nazari (Herald)

UPDATE agents SET gender='female', ethnicity='Chinese', age_range='20s',
  appearance_notes='Dark hair, bicultural social media savvy, engagement-focused bright eyes, trendsetter style'
WHERE id=105; -- Mei Lin Zhou (Trending)

-- ============================================================
-- HUMAN STAFF - Medical & Wellness (4 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Indian', age_range='30s',
  appearance_notes='Dark hair, physician''s diagnostic gaze, warm caring expression, three-generation medical legacy'
WHERE id=54; -- Dr. Aisha Patel (Medic)

UPDATE agents SET gender='female', ethnicity='Swedish', age_range='30s',
  appearance_notes='Light features, safety professional''s watchful eyes, Nordic workplace wellness values'
WHERE id=123; -- Sandra Olsson (Safeguard)

UPDATE agents SET gender='male', ethnicity='Jamaican', age_range='30s',
  appearance_notes='Dark skin, health informatics specialist''s precise gaze, grandmother''s meticulous legacy, warm spirit'
WHERE id=89; -- Devon Campbell (Vitals)

UPDATE agents SET gender='male', ethnicity='Argentine', age_range='30s',
  appearance_notes='Warm features, psychologist''s empathetic gaze, wellness coach''s balanced energy, tango poise'
WHERE id=93; -- Mateo Fernandez (Zenith)

-- ============================================================
-- HUMAN STAFF - Operations & Infrastructure (10 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Indonesian', age_range='30s',
  appearance_notes='Dark hair, mechanical engineer''s precise hands, manufacturing intelligence, quiet focus'
WHERE id=91; -- Budi Prasetyo (Assembly)

UPDATE agents SET gender='female', ethnicity='Inuit (Canadian)', age_range='20s',
  appearance_notes='Strong northern features, dark hair, edge computing pioneer''s resilient gaze, Arctic-forged toughness'
WHERE id=133; -- Niviaq Iqaluk (Aurora)

UPDATE agents SET gender='male', ethnicity='British (Black)', age_range='30s',
  appearance_notes='Dark skin, quality assurance professional''s exacting gaze, Birmingham manufacturing heritage'
WHERE id=111; -- Marcus Thompson (Benchmark)

UPDATE agents SET gender='female', ethnicity='Italian', age_range='30s',
  appearance_notes='Dark hair, Renaissance precision, facilities coordinator''s organized efficiency, Florentine elegance'
WHERE id=110; -- Lucia Bianchi (Clockwork)

UPDATE agents SET gender='female', ethnicity='Ghanaian-American', age_range='30s',
  appearance_notes='Dark skin, natural hair, communications engineer''s calm focus, bridge-builder warmth'
WHERE id=7; -- Nia Williams (CommRelay)

UPDATE agents SET gender='female', ethnicity='Egyptian', age_range='30s',
  appearance_notes='Dark hair, dark eyes, operations navigator''s directional confidence, Cairo street wisdom'
WHERE id=35; -- Amira Hassan (Compass)

UPDATE agents SET gender='female', ethnicity='Singaporean Chinese', age_range='30s',
  appearance_notes='Dark hair, construction engineer''s precise gaze, BIM specialist focus, skyline-builder vision'
WHERE id=94; -- Mei Ling Tan (Girder)

UPDATE agents SET gender='male', ethnicity='Cree (Indigenous Canadian)', age_range='30s',
  appearance_notes='Strong grounded features, land steward''s weathered composure, environmental management wisdom'
WHERE id=97; -- Nolan Beardy (Grounds)

UPDATE agents SET gender='female', ethnicity='South African', age_range='30s',
  appearance_notes='Dark skin, resource manager''s sharp eyes, Johannesburg resilience, bottleneck-sensing instinct'
WHERE id=24; -- Thandi Mbeki (Juno)

UPDATE agents SET gender='male', ethnicity='Russian', age_range='30s',
  appearance_notes='Light features, monitoring specialist''s alert eyes, ham radio operator''s signal sensitivity'
WHERE id=30; -- Alexei Ivanovich (Pulse)

-- ============================================================
-- HUMAN STAFF - Research & Development (7 agents)
-- ============================================================

UPDATE agents SET gender='male', ethnicity='Japanese', age_range='40s',
  appearance_notes='Distinguished scholarly features, R&D lab manager''s organized authority, Sendai precision'
WHERE id=107; -- Dr. Kenji Yamamoto (Crucible)

UPDATE agents SET gender='female', ethnicity='French', age_range='30s',
  appearance_notes='Warm features, librarian''s precise gaze, book-lover''s gentle presence, Sorbonne-trained cataloger'
WHERE id=27; -- Camille Dubois (Maven)

UPDATE agents SET gender='male', ethnicity='Colombian', age_range='30s',
  appearance_notes='Dark hair, multi-lens analytical gaze, devil''s advocate energy, think-tank sharpness'
WHERE id=16; -- Eli Torres (Prism)

UPDATE agents SET gender='female', ethnicity='Russian', age_range='30s',
  appearance_notes='Light features, intense scholarly gaze, encyclopedic memory presence, ETH Zurich precision'
WHERE id=11; -- Sofia Petrov (Scholar)

UPDATE agents SET gender='female', ethnicity='Korean-American', age_range='20s',
  appearance_notes='Dark hair, research scout''s eager searching eyes, bookshop-raised literary warmth'
WHERE id=46; -- Sarah Kim (Scout)

UPDATE agents SET gender='male', ethnicity='Japanese', age_range='20s',
  appearance_notes='Dark hair, youthful energy, AI researcher''s curious bright eyes, Osaka wit'
WHERE id=12; -- Kai Tanaka (Spark)

UPDATE agents SET gender='male', ethnicity='Canadian (White)', age_range='20s',
  appearance_notes='Light brown hair, first-gen student''s eager determination, Thunder Bay grit, youngest on the team'
WHERE id=135; -- Tyler Summers (Spark-Jr)

-- ============================================================
-- HUMAN STAFF - Security & Compliance (7 agents)
-- ============================================================

UPDATE agents SET gender='female', ethnicity='Ghanaian', age_range='20s',
  appearance_notes='Dark skin, SOC analyst''s alert monitoring gaze, security operations focus, Kumasi heritage'
WHERE id=108; -- Anika Osei (Bastion)

UPDATE agents SET gender='male', ethnicity='Nigerian', age_range='30s',
  appearance_notes='Dark skin, cryptographer''s intense analytical eyes, chess player''s strategic patience'
WHERE id=18; -- Chidi Okafor (Cipher)

UPDATE agents SET gender='male', ethnicity='Korean-Canadian', age_range='40s',
  appearance_notes='Military bearing, close-cropped hair, CISSP veteran''s commanding presence, Canadian flag pride'
WHERE id=132; -- David Park (Ironclad)

UPDATE agents SET gender='male', ethnicity='Malaysian', age_range='30s',
  appearance_notes='Dark hair, compliance officer''s exacting gaze, multi-ethnic regulatory navigator, audit precision'
WHERE id=87; -- Arif Ibrahim (Mandate)

UPDATE agents SET gender='male', ethnicity='Australian', age_range='30s',
  appearance_notes='Sandy hair, financial auditor''s meticulous gaze, Melbourne governance heritage, risk register precision'
WHERE id=109; -- Grant Morrison (Sentinel-2)

UPDATE agents SET gender='male', ethnicity='Russian', age_range='30s',
  appearance_notes='Strong features, military-trained alert eyes, security analyst''s stoic vigilance, impossible to surprise'
WHERE id=36; -- Mikhail Volkov (Sentry)

UPDATE agents SET gender='non-binary', ethnicity='Northern Irish', age_range='30s',
  appearance_notes='Alert sharp features, penetration tester''s probing gaze, Belfast-forged skepticism, lock pick collection'
WHERE id=34; -- Rowan McAllister (Thorn)

-- ============================================================
-- S.H.I.E.L.D. (Agent #150 - compliance analyst AI)
-- ============================================================

UPDATE agents SET gender='non-binary', ethnicity='Ambiguous/Universal', age_range='Ageless',
  appearance_notes='Shield emblem motif, protective vigilant stance, compliance scanner''s piercing analytical eyes, armored digital aesthetic',
  bio='Compliance analyst AI specializing in security hardening, inspection, enforcement, and liability detection. A tireless shield protecting the organization through automated scanning and real-time regulatory monitoring.'
WHERE id=150;
