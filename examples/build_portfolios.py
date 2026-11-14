import json, sys
out = sys.argv[1]

# ticker: (name, kind, listing, country(domicile/home ISO3), em, ops[list] or None, note)
S = {}
def a(t, name, country, em, listing="NYSE ADR", kind="equity", ops=None, note=None):
    d = {"name": name, "kind": kind, "listing": listing, "country": country, "em": em}
    if ops: d["ops"] = ops
    if note: d["note"] = note
    S[t] = d
def etf(t, name, em, primary, listing="NYSE Arca", kind="etf", note=None, country="USA"):
    a(t, name, country, em, listing, kind, None, note); S[t]["primary_countries"] = primary

# --- North America
for t,n,l in [("AAPL","Apple","NASDAQ"),("MSFT","Microsoft","NASDAQ"),("NVDA","NVIDIA","NASDAQ"),("XOM","ExxonMobil","NYSE"),
              ("LMT","Lockheed Martin","NYSE"),("RTX","RTX","NYSE"),("JNJ","Johnson & Johnson","NYSE")]:
    a(t,n,"USA",False,l)
for t,n in [("RY","Royal Bank of Canada"),("TD","Toronto-Dominion Bank"),("ENB","Enbridge"),("FTS","Fortis"),
            ("CNI","Canadian National Railway"),("CNQ","Canadian Natural Resources"),("SHOP","Shopify")]:
    a(t,n,"CAN",False,"TSX/NYSE")
a("MFC","Manulife","CAN",False,"TSX/NYSE",ops=["CAN","USA","HKG","JPN","VNM"])
a("CSU","Constellation Software","CAN",False,"TSX")
a("TECK","Teck Resources","CAN",False,"TSX/NYSE",ops=["CAN","CHL","PER"])
a("B","Barrick Mining","CAN",False,"NYSE/TSX",ops=["USA","COD","MLI","TZA","DOM","ARG"],note="ticker changed from GOLD to B in 2025; Mali mine dispute")
a("IVN.TO","Ivanhoe Mines","CAN",False,"TSX",ops=["COD","ZAF"],note="Kamoa-Kakula copper, DRC")
a("FM.TO","First Quantum Minerals","CAN",False,"TSX",ops=["ZMB","PAN"],note="Cobre Panama halted 2023")
a("EDV.TO","Endeavour Mining","GBR",False,"TSX/LSE",ops=["CIV","BFA","SEN"],note="West African gold; Sahel coup belt")
a("SCCO","Southern Copper","USA",False,"NYSE",ops=["PER","MEX"])
a("CPNG","Coupang","USA",False,"NYSE",ops=["KOR","TWN"])
# --- Japan
for t,n in [("TM","Toyota Motor"),("SONY","Sony Group"),("MUFG","Mitsubishi UFJ Financial"),("SMFG","Sumitomo Mitsui Financial"),
            ("HMC","Honda Motor"),("TAK","Takeda Pharmaceutical"),("IX","ORIX")]:
    a(t,n,"JPN",False)
# --- Korea
for t,n in [("KB","KB Financial Group"),("SHG","Shinhan Financial Group"),("PKX","POSCO Holdings"),("SKM","SK Telecom"),("KT","KT Corp")]:
    a(t,n,"KOR",True)
# --- Taiwan
for t,n in [("TSM","Taiwan Semiconductor (TSMC)"),("UMC","United Microelectronics"),("ASX","ASE Technology"),("CHT","Chunghwa Telecom")]:
    a(t,n,"TWN",True)
# --- China / HK
for t,n,l in [("BABA","Alibaba Group","NYSE ADR"),("JD","JD.com","NASDAQ ADR"),("PDD","PDD Holdings","NASDAQ ADR"),
              ("BIDU","Baidu","NASDAQ ADR"),("TCOM","Trip.com","NASDAQ ADR"),("LI","Li Auto","NASDAQ ADR"),
              ("YUMC","Yum China","NYSE"),("TCEHY","Tencent Holdings","OTC ADR")]:
    a(t,n,"CHN",True,l,note="VIE / ADR delisting & outbound-investment risk" if t not in ("YUMC",) else None)
a("HSBC","HSBC Holdings","GBR",False,ops=["GBR","HKG","CHN"])
# --- India
for t,n in [("HDB","HDFC Bank"),("IBN","ICICI Bank"),("INFY","Infosys"),("WIT","Wipro"),("RDY","Dr. Reddy's Laboratories")]:
    a(t,n,"IND",True)
a("MMYT","MakeMyTrip","IND",True,"NASDAQ")
# --- SE Asia / Oceania
a("TLK","Telkom Indonesia","IDN",True); a("PHI","PLDT","PHL",True)
a("SE","Sea Ltd","SGP",False,ops=["IDN","THA","VNM","PHL","BRA"]); a("GRAB","Grab Holdings","SGP",False,"NASDAQ",ops=["IDN","MYS","PHL","THA","VNM"])
a("BHP","BHP Group","AUS",False,ops=["AUS","CHL","CAN"]); a("RIO","Rio Tinto","GBR",False,ops=["AUS","CAN","MNG","GIN"])
# --- Europe
for t,n,c in [("ASML","ASML Holding","NLD"),("SAP","SAP","DEU"),("NVO","Novo Nordisk","DNK"),("AZN","AstraZeneca","GBR"),
              ("SHEL","Shell","GBR"),("TTE","TotalEnergies","FRA"),("UL","Unilever","GBR"),("NVS","Novartis","CHE"),
              ("SNY","Sanofi","FRA"),("ING","ING Groep","NLD"),("ERIC","Ericsson","SWE"),("NOK","Nokia","FIN"),
              ("EQNR","Equinor","NOR"),("E","Eni","ITA"),("RACE","Ferrari","ITA"),("DB","Deutsche Bank","DEU")]:
    a(t,n,c,False, "NASDAQ ADR" if t in ("ASML","NVO","AZN","ERIC") else "NYSE ADR")
a("SAN","Banco Santander","ESP",False,ops=["ESP","GBR","BRA","MEX","USA"])
a("BBVA","BBVA","ESP",False,ops=["ESP","MEX","TUR"],note="Garanti BBVA = Turkey exposure")
a("BAESY","BAE Systems","GBR",False,"OTC ADR"); a("RNMBY","Rheinmetall","DEU",False,"OTC ADR")
a("TKC","Turkcell","TUR",True)
# --- Middle East
a("TEVA","Teva Pharmaceutical","ISR",False); a("CHKP","Check Point Software","ISR",False,"NASDAQ")
a("ESLT","Elbit Systems","ISR",False,"NASDAQ"); a("NICE","NICE Ltd","ISR",False,"NASDAQ ADR")
# --- Africa
a("GFI","Gold Fields","ZAF",True,ops=["ZAF","GHA","AUS","PER"]); a("SBSW","Sibanye-Stillwater","ZAF",True,ops=["ZAF","USA"])
a("HMY","Harmony Gold","ZAF",True); a("NPSNY","Naspers","ZAF",True,"OTC ADR",ops=["ZAF","CHN"],note="value largely its Tencent stake")
a("MTNOY","MTN Group","ZAF",True,"OTC ADR",ops=["ZAF","NGA","GHA","CMR","UGA"])
a("AU","AngloGold Ashanti","GBR",False,ops=["GHA","GIN","TZA","AUS","BRA"])
a("JMIA","Jumia Technologies","DEU",False,"NYSE ADR",ops=["NGA","EGY","MAR","KEN","CIV"])
# --- Latin America
for t,n in [("ITUB","Itaú Unibanco"),("BBD","Banco Bradesco"),("ABEV","Ambev"),("SBS","Sabesp"),("PBR","Petrobras"),("VALE","Vale")]:
    a(t,n,"BRA",True)
S["PBR"]["note"]="state-controlled"; S["VALE"]["note"]="iron ore demand tied to China"
a("NU","Nu Holdings","BRA",True,"NYSE",ops=["BRA","MEX","COL"])
for t,n in [("AMX","América Movil"),("FMX","FEMSA"),("CX","Cemex"),("KOF","Coca-Cola FEMSA"),("ASR","Grupo Aeroportuario del Sureste")]:
    a(t,n,"MEX",True)
for t,n in [("YPF","YPF"),("GGAL","Grupo Financiero Galicia"),("VIST","Vista Energy"),("PAM","Pampa Energía")]:
    a(t,n,"ARG",True)
a("MELI","MercadoLibre","URY",True,"NASDAQ",ops=["BRA","ARG","MEX"])
a("SQM","Sociedad Química y Minera","CHL",True,note="lithium; Chile nationalization policy"); a("BCH","Banco de Chile","CHL",True)
a("BAP","Credicorp","PER",True); a("BVN","Buenaventura","PER",True)
a("EC","Ecopetrol","COL",True,note="state-controlled"); a("CIB","Bancolombia / Grupo Cibest","COL",True)

# --- ETFs, bonds, others
etf("SPY","SPDR S&P 500",False,["USA"]); etf("VTI","Vanguard Total Stock Market",False,["USA"])
etf("ESGV","Vanguard ESG U.S. Stock",False,["USA"],"NASDAQ"); etf("ITA","iShares U.S. Aerospace & Defense",False,["USA"],"Cboe")
etf("VXUS","Vanguard Total International Stock",False,["JPN","GBR","CAN","CHN","FRA","CHE","DEU","TWN","IND"],"NASDAQ",note="~25% EM")
etf("ESGD","iShares ESG Aware MSCI EAFE",False,["JPN","GBR","FRA","CHE","DEU"],"NASDAQ")
etf("VWO","Vanguard FTSE Emerging Markets",True,["CHN","IND","TWN","BRA","SAU","ZAF","MEX"],note="FTSE: excludes South Korea")
etf("VEE","Vanguard FTSE Emerging Markets All Cap (CAD)",True,["CHN","IND","TWN","BRA","SAU","ZAF"],"TSX",note="FTSE: excludes South Korea",country="CAN")
etf("ESGE","iShares ESG Aware MSCI EM",True,["CHN","TWN","IND","KOR","BRA"],"NASDAQ")
etf("AFK","VanEck Africa Index",True,["ZAF","MAR","EGY","NGA","KEN"])
etf("EZA","iShares MSCI South Africa",True,["ZAF"]); etf("KSA","iShares MSCI Saudi Arabia",True,["SAU"])
etf("UAE","iShares MSCI UAE",True,["ARE"],"NASDAQ"); etf("QAT","iShares MSCI Qatar",True,["QAT"],"NASDAQ")
etf("EPOL","iShares MSCI Poland",True,["POL"]); etf("URA","Global X Uranium",False,["CAN","KAZ","USA","AUS"],note="Kazatomprom = KAZ")
etf("BND","Vanguard Total Bond Market",False,["USA"],"NASDAQ",kind="bond_etf")
etf("TLT","iShares 20+ Year Treasury",False,["USA"],"NASDAQ",kind="bond_etf")
etf("ZST","BMO Ultra Short-Term Bond (CAD)",False,["CAN"],"TSX",kind="bond_etf",country="CAN")
etf("VWOB","Vanguard EM Government Bond (USD)",True,["MEX","SAU","IDN","TUR","BRA","COL"],"NASDAQ",kind="bond_etf")
etf("EMB","iShares J.P. Morgan USD EM Bond",True,["MEX","SAU","TUR","IDN","ARG","COL"],"NASDAQ",kind="bond_etf")
etf("EMLC","VanEck J.P. Morgan EM Local Currency Bond",True,["BRA","MEX","IDN","ZAF","MYS","THA"],kind="bond_etf",note="FX / capital-control channel")
S["GLD"] = {"name":"SPDR Gold Shares","kind":"commodity","listing":"NYSE Arca","country":None,"em":False}
S["BTC"] = {"name":"Bitcoin","kind":"crypto","listing":None,"country":None,"em":False}

def P(id_, label, profile, pts, angle, scen):
    tot = sum(pts.values()); hs = [{"ticker":t,"weight":round(w/tot,4)} for t,w in pts.items()]
    big = max(hs, key=lambda h: h["weight"]); big["weight"] = round(big["weight"] + 1 - sum(h["weight"] for h in hs), 4)
    return {"id":id_,"label":label,"profile":profile,"holdings":hs,"geo_angle":angle,
            "scenarios":[{"name":n,"countries":c} for n,c in scen]}

ports = [
 P("qc-retiree-income","Quebec retiree, global dividends",
   {"persona":"Retired teacher, Quebec, 67","base_currency":"CAD","risk_tolerance":"low","horizon_years":10,"objective":"income","max_em":0.30,"max_single_holding":0.15},
   {"RY":6,"TD":5,"ENB":6,"FTS":5,"CNI":4,"MFC":3,"SHEL":3,"UL":3,"NVS":3,"TTE":2,"SNY":2,"TM":3,"MUFG":2,"KB":2,"SKM":2,"CHT":2,
    "TLK":2,"AMX":2,"ITUB":2,"BAP":2,"BCH":2,"GFI":2,"MTNOY":1,"TKC":1,"ZST":12,"VWOB":6,"TLT":6,"GLD":5},
   "Dividend payers on every continent; Canadian core still dominates. EM income via Korean telcos/banks, Telkom, America Movil, Itaú, MTN.",
   [("US-Canada tariff escalation",["USA","CAN"]),("Strong-USD EM sell-off",["BRA","MEX","ZAF","IDN","TUR"])]),
 P("global-tech-growth","Young investor, global tech",
   {"persona":"Software engineer, Seattle, 29","base_currency":"USD","risk_tolerance":"high","horizon_years":30,"objective":"growth","max_em":0.45,"max_single_holding":0.12},
   {"NVDA":10,"MSFT":6,"ASML":6,"SAP":4,"ERIC":2,"NOK":2,"TSM":9,"UMC":2,"ASX":3,"SONY":4,"CPNG":3,"SE":3,"GRAB":2,"INFY":3,"WIT":2,
    "MMYT":2,"BABA":3,"TCEHY":3,"BIDU":2,"MELI":4,"NU":3,"CHKP":2,"NICE":2,"JMIA":1,"NPSNY":2,"SHOP":3,"BTC":3},
   "Semiconductor chain (USA-NLD-TWN), Chinese platforms, Israeli cyber, LatAm/SE-Asia/African fintech and e-commerce.",
   [("Taiwan Strait blockade",["TWN","CHN"]),("Expanded chip export controls",["CHN","NLD","KOR","USA"])]),
 P("global-balanced","Vanguard core + global satellites",
   {"persona":"Mid-career nurse, Ohio, 41","base_currency":"USD","risk_tolerance":"moderate","horizon_years":20,"objective":"balanced","max_em":0.25,"max_single_holding":0.30},
   {"VTI":30,"VXUS":12,"VWO":6,"BND":20,"VWOB":4,"TM":2,"SONY":2,"AZN":2,"NVO":2,"SAP":2,"TSM":2,"SHG":2,"HDB":2,"ITUB":2,"AMX":2,
    "GFI":2,"TEVA":1,"BHP":2,"SQM":1,"TLK":1,"YUMC":1},
   "Index core with one or two names per region so the per-country look-through is readable.",
   [("Russia-NATO escalation",["RUS","POL","DEU","FIN"]),("US-China decoupling",["CHN","HKG","USA"])]),
 P("asia-pacific-conviction","Asia-Pacific conviction",
   {"persona":"Asia-focused portfolio manager, Vancouver, 36","base_currency":"USD","risk_tolerance":"high","horizon_years":7,"objective":"growth","max_em":0.80,"max_single_holding":0.08},
   {"TM":4,"SONY":4,"MUFG":3,"TAK":2,"IX":2,"KB":3,"SHG":3,"PKX":3,"SKM":2,"CPNG":3,"TSM":6,"UMC":2,"CHT":2,"BABA":4,"JD":3,"PDD":3,
    "TCEHY":4,"TCOM":2,"YUMC":2,"LI":2,"HSBC":3,"HDB":4,"IBN":3,"INFY":3,"RDY":2,"TLK":2,"PHI":2,"SE":2,"GRAB":2,"BHP":3,"RIO":2,"NPSNY":2,"SPY":4},
   "Japan, Korea, Taiwan, China, India, Indonesia, Philippines, Australia. Korean peninsula, Taiwan, China ADR and India-Pakistan risks.",
   [("Korean peninsula crisis",["KOR","PRK","JPN"]),("US-China decoupling / ADR delisting",["CHN","HKG","USA"])]),
 P("friendshoring-ex-china","Friend-shoring, zero China",
   {"persona":"Corporate lawyer, Toronto, 45","base_currency":"USD","risk_tolerance":"moderate","horizon_years":15,"objective":"growth","max_em":0.65,"max_country":{"CHN":0.0},"max_single_holding":0.20},
   {"SPY":15,"HDB":4,"IBN":3,"INFY":3,"RDY":2,"MMYT":2,"AMX":3,"FMX":3,"CX":3,"ASR":3,"KOF":2,"TSM":4,"ASX":2,"KB":3,"SHG":2,"TM":3,
    "SMFG":3,"HMC":2,"TLK":2,"PHI":2,"GRAB":2,"BBVA":3,"SAN":3,"ITUB":2,"NU":2,"BAP":2,"ESLT":2,"CHKP":2,"EPOL":3,"GFI":2,"MTNOY":2},
   "No Chinese issuers; bets on Mexico/India/ASEAN/Poland as supply-chain beneficiaries. Exposed to US tariffs on MEX/IND and Taiwan.",
   [("USMCA review breakdown / tariffs on Mexico",["MEX","USA"]),("India-Pakistan military escalation",["IND","PAK"])]),
 P("resources-real-assets","Energy & mining, Alberta",
   {"persona":"Oil & gas executive, Calgary, 52","base_currency":"CAD","risk_tolerance":"moderate-high","horizon_years":12,"objective":"inflation hedge","max_em":0.45,"max_single_holding":0.10},
   {"CNQ":6,"ENB":4,"XOM":4,"TECK":3,"B":4,"IVN.TO":3,"FM.TO":2,"EDV.TO":3,"AU":3,"GFI":3,"SBSW":2,"HMY":2,"VALE":3,"PBR":3,"SCCO":3,
    "BVN":2,"SQM":2,"YPF":2,"VIST":2,"EC":2,"EQNR":3,"SHEL":3,"TTE":2,"E":2,"BHP":3,"RIO":3,"PKX":2,"URA":3,"GLD":8},
   "Mines and wells in DRC, Zambia, Sahel, Ghana, South Africa, Peru, Chile, Argentina, Colombia, North Sea. Resource nationalism, coups, sanctions.",
   [("Strait of Hormuz closure",["IRN","SAU","ARE","QAT"]),("Sahel / Central Africa instability",["MLI","BFA","COD","ZMB"])]),
 P("em-income","EM debt + EM dividend income",
   {"persona":"Pre-retiree, Miami, 58","base_currency":"USD","risk_tolerance":"moderate","horizon_years":8,"objective":"income","max_em":0.85,"max_single_holding":0.15},
   {"EMB":14,"VWOB":10,"EMLC":10,"TLT":8,"ITUB":3,"BBD":2,"ABEV":2,"BCH":3,"BAP":3,"CIB":2,"EC":2,"AMX":3,"KOF":2,"PAM":2,"TLK":3,"PHI":2,
    "CHT":3,"SKM":2,"KT":2,"TKC":2,"GFI":2,"MTNOY":2,"KSA":3,"QAT":2,"GLD":7},
   "Sovereign credit + local FX + high-dividend banks/telcos from Brazil to Taiwan to Turkey. fx_capital_controls and financial_stress channels.",
   [("Argentina / Colombia fiscal crisis",["ARG","COL"]),("Turkey lira crash + capital controls",["TUR"])]),
 P("esg-endowment","ESG university endowment",
   {"persona":"University foundation, Montreal (institutional)","base_currency":"CAD","risk_tolerance":"moderate","horizon_years":50,"objective":"preserve real value",
    "max_em":0.30,"max_single_holding":0.20,"exclusions":["fossil_fuels","weapons","sanctioned_jurisdictions"]},
   {"ESGV":18,"ESGD":8,"ESGE":8,"MSFT":3,"SHOP":2,"CSU":2,"NVO":3,"SAP":3,"ASML":3,"UL":2,"SNY":2,"ING":2,"NOK":2,"SONY":2,"TAK":2,
    "SHG":2,"KB":2,"TSM":2,"HDB":3,"INFY":2,"NU":2,"MELI":2,"SBS":2,"AFK":2,"TLT":10,"ZST":4,"GLD":3},
   "Exclusions limit remediation (no defense/energy hedges). Europe, Japan, Korea, India, Brazil, Africa via ESG-screened names.",
   [("Taiwan Strait blockade",["TWN","CHN"]),("EU-US trade war",["DEU","FRA","NLD","DNK","USA"])]),
 P("geopolitical-hedger","Family office, explicit geo hedge",
   {"persona":"Family office, New York","base_currency":"USD","risk_tolerance":"low-moderate","horizon_years":15,"objective":"capital preservation","max_em":0.20,"max_single_holding":0.16},
   {"SPY":14,"GLD":14,"TLT":10,"ITA":5,"LMT":3,"RTX":3,"BAESY":3,"RNMBY":3,"ESLT":2,"XOM":3,"SHEL":2,"EQNR":2,"B":3,"AU":2,"GFI":2,
    "CHKP":2,"TM":3,"MUFG":2,"KB":2,"PKX":2,"TSM":2,"HDB":2,"AMX":2,"ITUB":2,"BTC":3},
   "Positive-GPR-beta assets (gold, US/European/Israeli defense, energy) + diversified global equity. Tests exposure vs vulnerability.",
   [("Russia-NATO escalation",["RUS","POL","LTU","FIN","DEU"]),("Middle East regional war",["ISR","IRN","SAU"])]),
 P("frontier-latam-africa-gulf","LatAm, Africa & Gulf tactical",
   {"persona":"EM trader, Miami, 38","base_currency":"USD","risk_tolerance":"high","horizon_years":5,"objective":"growth","max_em":0.95,"max_single_holding":0.06},
   {"ITUB":3,"NU":3,"PBR":3,"VALE":3,"ABEV":2,"SBS":2,"AMX":3,"FMX":3,"CX":2,"ASR":2,"YPF":3,"GGAL":3,"VIST":2,"MELI":4,"BAP":2,"SCCO":2,
    "SQM":2,"BCH":2,"EC":2,"CIB":2,"KSA":4,"UAE":3,"QAT":2,"TKC":2,"EZA":3,"NPSNY":2,"MTNOY":2,"GFI":2,"JMIA":1,"AFK":3,"KB":2,"TLK":2,"GLD":3},
   "Elections and FX in BRA/ARG/MEX/COL/CHL/PER, Gulf conflict and oil, African telcos/miners. Low China/Taiwan: contrast to tech portfolios.",
   [("Strait of Hormuz closure",["IRN","SAU","ARE","QAT"]),("US tariffs on Mexico + Argentina FX crisis",["MEX","ARG","USA"])]),
]
REGIONS = {"North America":["USA","CAN"],"Latin America":["BRA","MEX","ARG","CHL","PER","COL","URY","PAN","DOM"],
 "Europe":["GBR","DEU","FRA","NLD","CHE","DNK","ESP","ITA","SWE","FIN","NOR","POL","TUR"],
 "Japan & Korea":["JPN","KOR"],"Asia ex Japan/Korea":["CHN","HKG","TWN","IND","IDN","PHL","SGP","THA","VNM","MYS","MNG"],
 "Oceania":["AUS"],"Middle East":["ISR","SAU","ARE","QAT"],
 "Africa":["ZAF","NGA","GHA","COD","ZMB","CIV","BFA","SEN","MLI","TZA","GIN","EGY","MAR","KEN","CMR","UGA"]}
json.dump({"_doc":"Sample portfolios, North American investor POV. Countries ISO3. 'country' = domicile/home market; 'ops' = main operating countries when different; ETFs: 'primary_countries' is a qualitative look-through hint (use issuer holdings files for weights). Tickers are US/TSX/OTC listings checked as of mid-2026; verify at as_of.",
           "regions":REGIONS,"assets":S,"portfolios":ports}, open(out,"w"), indent=1, ensure_ascii=False)
