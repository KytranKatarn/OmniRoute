; Zone: what-the-fact.com  — authoritative, served by our own gdnsd nameservers.
; Apex + www are GEO-ROUTED to the nearest healthy Watch edge (DYNA -> geoip plugin).
; #4319 / ADR-010. NS = our 3 geo-spread outposts.
;
; !!! STAGE-4 CUTOVER FOOTGUN !!!  Before delegating NS at the registrar, MIRROR the
; FULL current Hostinger zone here (MX, SPF/DKIM/DMARC TXT, every subdomain). A dropped
; MX = mail outage. Diff against the live Hostinger export; nothing may be lost.
; The records below are the EDGE-ROUTING skeleton only — NOT a complete zone yet.

@	300	SOA	ns1.what-the-fact.com. hostmaster.what-the-fact.com. (
			1          ; serial (bump on every change)
			7200       ; refresh
			1800       ; retry
			1209600    ; expire
			300        ; negative-cache TTL
			)

@	300	NS	ns1.what-the-fact.com.
@	300	NS	ns2.what-the-fact.com.
@	300	NS	ns3.what-the-fact.com.

; Nameserver glue (must match the registrar glue records).
ns1	300	A	76.13.107.109	; Outpost-US (NA)   -- needs task #4552 (hostname fix) first
ns2	300	A	2.24.130.153	; Outpost-UK (EU)
ns3	300	A	156.67.217.86	; Outpost-Singapore (APAC)

; Apex + www -> nearest healthy edge. Short TTL so health failover propagates fast.
@	60	DYNA	geoip!wtf_edge
www	60	DYNA	geoip!wtf_edge

; --- TODO at Stage 4: copy verbatim from the live Hostinger zone ---
; MX, _dmarc TXT, SPF TXT, DKIM TXT, mta-sts, any other subdomains, .tech if folded in.
