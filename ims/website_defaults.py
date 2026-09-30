"""
Default website content & price list.

These reproduce what the public site showed when it was hard-coded, so moving
to the database changes nothing visually until someone edits a value in
HQ -> Website Manager. Used by the data migration and the "Seed defaults"
button (both are idempotent and never overwrite an edited value).
"""

# (section, key, label, value)
CONTENT_DEFAULTS = [
    ('hero', 'hero_badge', 'Hero badge (areas served)', 'Now serving Jozini, Mkuze, Hluhluwe & Northern KZN'),
    ('hero', 'hero_subtitle', 'Hero paragraph',
     'From robust network infrastructure and bulletproof cybersecurity to custom software and seamless POS systems — '
     'we manage your technology so you can focus on growth.'),
    ('hero', 'hero_stat_devices', 'Stat 1 — number (e.g. 500+)', '500+'),
    ('hero', 'hero_stat_devices_label', 'Stat 1 — caption', 'Devices Repaired'),
    ('hero', 'hero_stat_satisfaction', 'Stat 2 — number (e.g. 98%)', '98%'),
    ('hero', 'hero_stat_satisfaction_label', 'Stat 2 — caption', 'Client Satisfaction'),
    ('hero', 'hero_stat_years', 'Stat 3 — number (e.g. 5+ Yrs)', '5+ Yrs'),
    ('hero', 'hero_stat_years_label', 'Stat 3 — caption', 'In Business'),
    ('hero', 'hero_stat_turnaround', 'Stat 4 — number (e.g. 24h)', '24h'),
    ('hero', 'hero_stat_turnaround_label', 'Stat 4 — caption', 'Turnaround'),
    ('services', 'pricing_headline', 'Pricing section headline', 'Clear, Upfront Costs'),
    ('services', 'pricing_note', 'Pricing footnote', 'All prices exclude VAT where applicable. Final quotes provided before any work begins.'),
    ('services', 'consultation_banner', 'Consultation offer banner', '🎉 Discounted Consultation Block (5 Hrs) — Now R349.99!'),
    ('cta', 'cta_headline', 'Call-to-action headline', 'Ready to transform your IT?'),
    ('contact', 'contact_email', 'Contact email', 'infor@rehumile.co.za'),
    ('contact', 'contact_email_note', 'Email caption', 'For quotes, general enquiries & support'),
    ('contact', 'contact_phone', 'Contact phone (as displayed)', '068 397 3484'),
    ('contact', 'contact_phone_intl', 'Phone (footer format)', '+27 68 397 3484'),
    ('contact', 'contact_phone_link', 'Phone number for tap-to-call (international, no spaces)', '+27683973484'),
    ('contact', 'contact_phone_note', 'Phone caption', 'Call or WhatsApp us anytime'),
    ('contact', 'contact_location', 'Location', 'Jozini, KwaZulu-Natal'),
    ('contact', 'contact_location_note', 'Location caption', 'Serving Jozini, Mkuze, Hluhluwe & surrounding areas'),
    ('contact', 'contact_hours', 'Business hours', 'Monday – Friday: 08:00 – 17:00'),
    ('contact', 'contact_hours_note', 'Business hours caption', 'Urgent support available on weekends by arrangement'),
]

# Keys the public page actually reads — the editor marks everything else "not on site yet".
LIVE_KEYS = {k for _, k, _, _ in CONTENT_DEFAULTS}

# Placeholder values an earlier version of the editor seeded that contradict the real site.
LEGACY_FAKE_VALUES = {
    'contact_email': 'info@rehumile.co.za',
    'contact_phone': '+27 (0) 11 000 0000',
    'hero_stat_years': '5+',
}
LEGACY_FAKE_ADDRESS = 'Johannesburg, Gauteng, South Africa'

# group, category, name, price, unit, description, prefix, featured
PRICE_DEFAULTS = [
    ('hardware', 'it_support', 'PC/Laptop Troubleshooting & Diagnostic Report', '249.99', '', '', ''),
    ('hardware', 'it_support', 'Virus Removal + Firmware Updates + Support Assist', '379.99', '', '', ''),
    ('hardware', 'it_support', 'Remote Assistance + Computer Health Check', '119.99', 'per 30 min', '', ''),
    ('hardware', 'it_support', 'Local House Call / Assistance Fee', '249.99', 'Excl. Services', '', ''),
    ('hardware', 'hardware', 'Printer Installation & Maintenance', '299.99', '', '', 'From'),
    ('software', 'software', 'Latest Windows 11 OS Upgrade', '599.99', '', '', ''),
    ('software', 'software', 'Windows 10 OS Upgrade', '479.00', '', '', ''),
    ('software', 'software', 'Ms Office 365 (Latest) Permanent Subscription', '349.99', '', '', ''),
    ('software', 'software', 'Ms Office 2019 Permanent Subscription', '299.99', '', '', ''),
    ('software', 'software', 'Ms Office 2016 Permanent Subscription', '269.99', '', '', ''),
    ('pos', 'other', 'Basic Retail Software Provisioning', '1499.00', 'Single-terminal offline standalone inventory', '', ''),
    ('pos', 'other', 'Hardware Peripherals Configuration', '699.99', 'Printer, scanner, cash drawer setup', '', ''),
    ('pos', 'other', 'Smart Speedpoint Integration', '349.99', 'Linking independent card machines', '', ''),
    ('pos', 'other', 'On-Site Operations & Staff Training', '450.00', 'Cashing up, product logging, reporting', '', ''),
    ('combo', 'software', 'Rehumile Combo 01', '1299.99', '',
     'Ms Office 365 Permanent + Desired Apps + Support Assist + Windows/Firmware Updates', ''),
    ('combo', 'software', 'Rehumile Combo 02', '999.99', '',
     'Windows 10/11 Upgrade + Ms Office 365 Permanent + Basic Support', ''),
    ('combo', 'other', 'Rehumile POS Combo 03', '2249.99', '',
     'POS Software Setup + Peripheral Config + Staff Training + Initial Stock Import', ''),
]
