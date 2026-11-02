"""PIX "copia e cola" (BR Code estático): módulo puro, sem estado e sem dependências do projeto."""
import unicodedata


def _tlv(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    crc = 0xFFFF
    for byte in texto.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def pix_copia_e_cola(chave: str, nome: str, cidade: str, valor: float | None = None) -> str:
    """Gera o código PIX 'copia e cola' (estático, com valor). O cliente cola no app do banco."""
    conta = _tlv("00", "br.gov.bcb.pix") + _tlv("01", chave)
    corpo = (_tlv("00", "01") + _tlv("26", conta) + _tlv("52", "0000") + _tlv("53", "986")
             + (_tlv("54", f"{valor:.2f}") if valor else "")
             + _tlv("58", "BR") + _tlv("59", _ascii(nome)[:25]) + _tlv("60", _ascii(cidade)[:15])
             + _tlv("62", _tlv("05", "***")) + "6304")
    return corpo + _crc16(corpo)
