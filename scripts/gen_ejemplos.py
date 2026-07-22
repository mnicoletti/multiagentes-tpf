from decimal import Decimal, ROUND_HALF_UP
from datetime import date
import openpyxl

MEP = Decimal("1509.845288326301")
CENT = Decimal("0.01")
def q(x): return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)

def build(path, *, titular, comitente, as_of, cash_ars, cash_usd_lines, acciones, bonos, cedears):
    """cash_usd_lines: list of (descripcion, qty_usd). acciones/bonos/cedears: list of (ticker,desc,qty,precio)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Estado de Cuenta al {as_of.strftime('%d-%m-%Y')}"
    rows = []
    # compute cash MONEDAS
    cash_rows = []
    valor_sum = Decimal("0")
    for desc, qty in cash_usd_lines:
        qd = Decimal(str(qty))
        valor = q(qd * MEP)
        valor_sum += valor
        cash_rows.append(("USD", desc, float(qd), float(MEP), float(valor)))
    ars = q(Decimal(str(cash_ars)))
    valor_sum += ars
    cash_rows.append(("$", "Peso", float(ars), 1, float(ars)))

    # positions
    def pos_block(items):
        block = []
        subtotal = Decimal("0")
        for tk, desc, qty, precio in items:
            valor = q(Decimal(str(qty)) * Decimal(str(precio)))
            subtotal += valor
            block.append((tk, desc, qty, precio, valor))
        return block, subtotal
    acc_b, acc_sub = pos_block(acciones)
    bon_b, bon_sub = pos_block(bonos)
    ced_b, ced_sub = pos_block(cedears)

    total_ars = q(valor_sum + acc_sub + bon_sub + ced_sub)
    total_usd = q(total_ars / MEP)
    def pct(v): return float((Decimal(str(v)) / total_ars) * 100)

    # header
    rows.append(["ESTADO DE CUENTA"])
    rows.append([])
    rows.append(["TITULAR", None, "FECHA"])
    rows.append([titular, None, as_of.strftime("%d/%m/%Y")])
    rows.append(["COMITENTE"])
    rows.append([comitente])
    rows.append([])
    rows.append(["TOTAL CARTERA EXPRESADO EN PESOS $", None, float(total_ars)])
    rows.append(["TOTAL USD EXPRESADO EN DOLARES U$D", None, float(total_usd)])
    rows.append([])
    rows.append(["POR TIPO DE ACTIVO"])
    rows.append([])
    # MONEDAS
    rows.append(["MONEDAS"])
    rows.append(["MONEDA", "DESCRIPCIÓN", "CANT. DISPONIBLE", "PRECIO", "VALOR CORRIENTE", "% CARTERA"])
    cash_valor_total = Decimal("0")
    for mon, desc, qty, precio, valor in cash_rows:
        rows.append([mon, desc, qty, precio, valor, pct(valor)])
        cash_valor_total += Decimal(str(valor))
    rows.append(["SUBTOTAL", None, None, None, float(q(cash_valor_total)), pct(q(cash_valor_total))])
    rows.append([])
    # asset sections
    ASSET_HEADER = ["ESPECIE", "DESCRIPCIÓN", "CANT. DISPONIBLE", "CANT. GARANTÍA", "PRECIO",
                    "VALOR MONEDA COTIZACIÓN", "VALOR CORRIENTE", "% CARTERA"]
    for name, block, sub in (("ACCIONES", acc_b, acc_sub), ("BONOS", bon_b, bon_sub), ("CEDEARS", ced_b, ced_sub)):
        rows.append([name])
        rows.append(list(ASSET_HEADER))
        for tk, desc, qty, precio, valor in block:
            rows.append([tk, desc, qty, 0, precio, float(valor), float(valor), pct(valor)])
        rows.append(["SUBTOTAL", None, None, None, None, None, float(q(sub)), pct(q(sub))])
        rows.append([])

    for r in rows:
        ws.append(r)
    wb.save(path)
    return dict(total_ars=float(total_ars), total_usd=float(total_usd),
               n_pos=len(acc_b)+len(bon_b)+len(ced_b))

D = "docs/ejemplos"
out = {}

# 1) Conservador hard-dollar (dolarizado, baja concentración AR)
out["01"] = build(f"{D}/comitente-01-conservador-hard-dollar.xlsx",
    titular="PEREZ ANA LAURA", comitente="300111", as_of=date(2026,7,21),
    cash_ars=1850000,
    cash_usd_lines=[("CV7000 - DIVISA OPERABLES", 8200.0), ("U$Renta", 3100.0)],
    acciones=[("GGAL","Grupo Financiero Galicia",40,7965),
              ("PAMP","PAMPA ENERGIA S.A. ESCRIT. 1 VOTO",55,5475)],
    bonos=[("AL30","BONOS ARGENTINA USD 2030 L.A",9800,858.8),
           ("GD35","Bonos Globales Argentina USD Step Up 2035",5200,1258.9),
           ("GD38","Bonos Globales Argentina USD Step Up 2038",1400,1308)],
    cedears=[("SPY","Spdr S&P 500",120,19610),
             ("GLD","CEDEAR ETF SPDR GOLD TRUST",210,11780)])

# 2) Agresivo concentrado en energía AR (single-name risk)
out["02"] = build(f"{D}/comitente-02-agresivo-energia.xlsx",
    titular="GOMEZ CARLOS ALBERTO", comitente="300222", as_of=date(2026,7,21),
    cash_ars=420000,
    cash_usd_lines=[("CV10000 - BILLETE OPERABLES", 900.0)],
    acciones=[("YPFD","YPF",210,80625),
              ("PAMP","PAMPA ENERGIA S.A. ESCRIT. 1 VOTO",380,5475),
              ("CEPU","CENTRAL PUERTO S.A. ESCRIT. B",520,2340),
              ("TGNO4","TRANS. GAS DEL NORTE C ORD $ ESC",300,4077.5),
              ("METR","METROGAS B 1 V. ESCRIT.",610,2150)],
    bonos=[("GD35","Bonos Globales Argentina USD Step Up 2035",900,1258.9)],
    cedears=[("VIST","Vista Energy",42,34300),
             ("XLU","CEDEAR UTILITIES SELECT SECTOR SPDR FUND",95,4707.5)])

# 3) Diversificado CEDEARs / US tech
out["03"] = build(f"{D}/comitente-03-diversificado-cedears.xlsx",
    titular="ROSSI MARIA FERNANDA", comitente="300333", as_of=date(2026,7,21),
    cash_ars=1200000,
    cash_usd_lines=[("CV7000 - DIVISA OPERABLES", 4500.0), ("U$Renta", 1800.0)],
    acciones=[("BMA","Banco Macro",48,14500),
              ("GGAL","Grupo Financiero Galicia",90,7965),
              ("PAMP","PAMPA ENERGIA S.A. ESCRIT. 1 VOTO",120,5475)],
    bonos=[("GD35","Bonos Globales Argentina USD Step Up 2035",1600,1258.9),
           ("AL30","BONOS ARGENTINA USD 2030 L.A",2200,858.8)],
    cedears=[("AAPL","Apple",70,25720),("NVDA","Nvidia Corporation",180,13540),
             ("GOOGL","Alphabet",150,9430),("AMZN","Amazon",240,2705),
             ("QQQ","Invesco Qqq Trust",22,55700),("SPY","Spdr S&P 500",90,19610),
             ("GLD","CEDEAR ETF SPDR GOLD TRUST",60,11780)])

# 4) Cartera chica / inicial (minimal)
out["04"] = build(f"{D}/comitente-04-cartera-inicial.xlsx",
    titular="LOPEZ JUAN MARTIN", comitente="300444", as_of=date(2026,7,21),
    cash_ars=280000,
    cash_usd_lines=[("CV10000 - BILLETE OPERABLES", 350.0)],
    acciones=[("GGAL","Grupo Financiero Galicia",25,7965),
              ("PAMP","PAMPA ENERGIA S.A. ESCRIT. 1 VOTO",30,5475)],
    bonos=[("AL30","BONOS ARGENTINA USD 2030 L.A",600,858.8)],
    cedears=[("SPY","Spdr S&P 500",12,19610),("AAPL","Apple",8,25720)])

for k,v in out.items():
    print(k, v)
