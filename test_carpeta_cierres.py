"""Pruebas de la carpeta de cierres: el .txt VACÍO que deja `clear_txt_file`.

    python -m unittest test_carpeta_cierres -v

Carpeta temporal real y el cliente de pruebas de Flask con JSON (como lo manda
el POS). A diferencia de `test.py`, afirman el contenido de la respuesta.

EL CASO (QA del PR #1624 de gleiros, Caja 11 de staging, 28-09-2026):
`clear_txt_file` archiva el cierre y recrea un .txt VACÍO con el mismo nombre.
El cierre siguiente llegó con otro nombre (lleva la fecha) y `_un_solo_txt`
contaba los dos: «No se encontró un único archivo TXT», el POS no encontró el
comprobante de un lote ya cerrado.
"""
import os
import shutil
import tempfile
import unittest

from main import app

VACIO = 'Cierre_Caja_caja_01_20260924.txt'
HOY = 'Cierre_Caja_caja_01_20260928.txt'
AYER = 'Cierre_Caja_caja_01_20260927.txt'
TEXTO_HOY = 'REPORTE DE CIERRE\nCIERRE: 28/09/2026 12:19:02\nTotal 0012 245.310,00 VES\n'
TEXTO_AYER = 'REPORTE DE CIERRE\nCIERRE: 27/09/2026 21:02:11\nTotal 0009 98.100,00 VES\n'


class CarpetaDeCierres(unittest.TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix='cierres ')
        self.addCleanup(shutil.rmtree, self.carpeta, True)
        self.cliente = app.test_client()

    def escribir(self, nombre, texto):
        with open(os.path.join(self.carpeta, nombre), 'w', encoding='cp1252', newline='') as fh:
            fh.write(texto)

    def post(self, ruta):
        respuesta = self.cliente.post(ruta, json={'pathToTxt': self.carpeta})
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.get_json()

    def txt(self):
        return sorted(n for n in os.listdir(self.carpeta) if n.endswith('.txt'))

    # --- el caso ---------------------------------------------------------

    def test_check_ignora_el_vacio_y_devuelve_el_comprobante(self):
        self.escribir(VACIO, '')
        self.escribir(HOY, TEXTO_HOY)
        datos = self.post('/api/check_txt_file')
        self.assertTrue(datos['exists'], datos)
        self.assertEqual(datos['file_name'], HOY)
        self.assertEqual(datos['data'][1], '800CIERRE: 28/09/2026 12:19:02')
        self.assertEqual(datos['vacios_ignorados'], [VACIO])

    def test_un_vacio_de_puros_espacios_tambien_se_ignora(self):
        self.escribir(VACIO, '  \n\n')
        self.escribir(HOY, TEXTO_HOY)
        self.assertEqual(self.post('/api/check_txt_file')['file_name'], HOY)

    def test_clear_archiva_el_comprobante_y_no_toca_el_vacio(self):
        self.escribir(VACIO, '')
        self.escribir(HOY, TEXTO_HOY)
        sha1 = self.post('/api/check_txt_file')['sha1']
        resultado = self.cliente.post('/api/clear_txt_file', json={
            'pathToTxt': self.carpeta, 'expected_sha1': sha1}).get_json()
        self.assertEqual(resultado['status'], 'OK', resultado)
        respaldo = os.listdir(os.path.join(self.carpeta, 'backup'))
        self.assertEqual(len(respaldo), 1)
        self.assertTrue(respaldo[0].startswith(HOY[:-4] + '_'))
        with open(os.path.join(self.carpeta, 'backup', respaldo[0]), encoding='cp1252', newline='') as fh:
            self.assertEqual(fh.read(), TEXTO_HOY)
        # El comprobante se recrea vacío (como siempre) y el vacío viejo sigue ahí.
        self.assertEqual(self.txt(), sorted([VACIO, HOY]))
        self.assertEqual(os.path.getsize(os.path.join(self.carpeta, HOY)), 0)

    def test_el_dia_siguiente_con_dos_vacios_tambien_encuentra_el_nuevo(self):
        self.escribir(VACIO, '')
        self.escribir(AYER, '')
        self.escribir(HOY, TEXTO_HOY)
        self.assertEqual(self.post('/api/check_txt_file')['file_name'], HOY)

    # --- lo que NO cambia ------------------------------------------------

    def test_dos_con_contenido_sigue_negandose(self):
        self.escribir(VACIO, '')
        self.escribir(AYER, TEXTO_AYER)
        self.escribir(HOY, TEXTO_HOY)
        datos = self.post('/api/check_txt_file')
        self.assertFalse(datos['exists'])
        self.assertEqual(datos['motivo'], 'varios_archivos')
        self.assertEqual(sorted(datos['archivos']), sorted([VACIO, AYER, HOY]))
        limpieza = self.post('/api/clear_txt_file')
        self.assertEqual(limpieza['status'], 'error')
        self.assertEqual(limpieza['motivo'], 'varios_archivos')
        self.assertFalse(os.path.isdir(os.path.join(self.carpeta, 'backup')), 'no se archiva nada')

    def test_un_archivo_ilegible_no_se_da_por_vacio(self):
        self.escribir(HOY, TEXTO_HOY)
        self.escribir(AYER, TEXTO_AYER)
        ruta = os.path.join(self.carpeta, AYER)
        os.chmod(ruta, 0)
        self.addCleanup(os.chmod, ruta, 0o644)
        if os.access(ruta, os.R_OK):
            self.skipTest('el usuario puede leer igual (root)')
        datos = self.post('/api/check_txt_file')
        self.assertFalse(datos['exists'], 'eligió el legible sin saber qué traía el otro')
        self.assertEqual(datos['motivo'], 'varios_archivos')

    def test_un_solo_vacio_como_siempre(self):
        self.escribir(HOY, '')
        datos = self.post('/api/check_txt_file')
        self.assertFalse(datos['exists'])
        self.assertEqual(datos['data'], [])
        self.assertEqual(datos['file_name'], HOY)

    def test_solo_vacios_no_hay_comprobante_ni_se_archiva(self):
        self.escribir(VACIO, '')
        self.escribir(AYER, '')
        datos = self.post('/api/check_txt_file')
        self.assertFalse(datos['exists'])
        self.assertEqual(datos['data'], [])
        self.assertEqual(datos['motivo'], 'solo_vacios')
        self.assertEqual(sorted(datos['archivos']), sorted([VACIO, AYER]))
        limpieza = self.post('/api/clear_txt_file')
        self.assertEqual(limpieza['status'], 'error')
        self.assertEqual(limpieza['motivo'], 'solo_vacios')
        self.assertEqual(self.txt(), sorted([VACIO, AYER]))

    def test_carpeta_sin_txt(self):
        datos = self.post('/api/check_txt_file')
        self.assertFalse(datos['exists'])
        self.assertEqual(datos['motivo'], 'cero_archivos')


if __name__ == '__main__':
    unittest.main()


class FinDeLineaWindows(unittest.TestCase):
    """El VPOS corre en Windows: sus .txt terminan las líneas en CRLF.

    El demonio desplegado (19747f4) abría en modo texto y Python convertía CRLF
    en LF, así que el POS recibía `800CIERRE: …` limpio. 1ef7e3e pasó a leer en
    BINARIO (bien: no puede fallar por codificación) pero `_comandos` sólo
    quitaba el `\\n`: cada comando llegaba a la impresora fiscal con un `\\r`
    colgando, y el POS comparaba/buscaba líneas con ese `\\r`.
    """

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix='cierres ')
        self.addCleanup(shutil.rmtree, self.carpeta, True)
        self.ruta = os.path.join(self.carpeta, HOY)
        with open(self.ruta, 'wb') as fh:
            fh.write(b'REPORTE DE CIERRE\r\nCIERRE: 28/09/2026 12:19:02\r\nTotal 0012 245.310,00 VES\r\n')
        self.cliente = app.test_client()

    def test_check_txt_file_sin_retorno_de_carro(self):
        datos = self.cliente.post('/api/check_txt_file', json={'pathToTxt': self.carpeta}).get_json()
        self.assertEqual(datos['data'], ['800REPORTE DE CIERRE', '800CIERRE: 28/09/2026 12:19:02',
                                         '800Total 0012 245.310,00 VES', '810Fin del documento.'])

    def test_get_txt_file_sin_retorno_de_carro(self):
        datos = self.cliente.post('/api/get_txt_file', json={'pathToTxt': self.ruta}).get_json()
        self.assertFalse(any('\r' in comando for comando in datos), datos)
        self.assertEqual(datos[1], '800CIERRE: 28/09/2026 12:19:02')
