"""Reserva de conexiones inactivas: sin base de datos (conexiones falsas)."""

import threading

from tinotify.real_remoto.almacen import _Reserva


class Conexion:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Reloj:
    t = 0.0

    def __call__(self):
        return self.t


def test_tomar_devuelve_la_ultima_devuelta_y_vacia_la_reserva():
    r = _Reserva(reloj=Reloj())
    a, b = Conexion(), Conexion()
    r.devolver(a)
    r.devolver(b)
    assert r.tomar() is b and r.tomar() is a and r.tomar() is None


def test_solo_se_guardan_tres_y_el_resto_se_cierra():
    r = _Reserva(maximo=3, reloj=Reloj())
    cons = [Conexion() for _ in range(5)]
    for c in cons:
        r.devolver(c)
    assert [c.closed for c in cons] == [False, False, False, True, True]


def test_una_conexion_vieja_o_cerrada_se_descarta_al_tomar():
    reloj = Reloj()
    r = _Reserva(edad_s=45, reloj=reloj)
    vieja, muerta, buena = Conexion(), Conexion(), Conexion()
    r.devolver(vieja)
    reloj.t = 30
    r.devolver(muerta)
    muerta.closed = True
    r.devolver(buena)
    reloj.t = 60                       # vieja: 60 s; buena y muerta: 30 s
    assert r.tomar() is buena
    assert r.tomar() is None and vieja.closed


def test_dos_hilos_nunca_reciben_la_misma_conexion():
    r = _Reserva(maximo=50, reloj=Reloj())
    for _ in range(50):
        r.devolver(Conexion())
    tomadas, cerrojo = [], threading.Lock()

    def sacar():
        while (c := r.tomar()) is not None:
            with cerrojo:
                tomadas.append(c)
    hilos = [threading.Thread(target=sacar) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len(tomadas) == 50 == len({id(c) for c in tomadas})
