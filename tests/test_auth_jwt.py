import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apu_tool.servicio.auth import ErrorAuth, verificar_token

ISS = "https://proj.supabase.co/auth/v1"


@pytest.fixture(scope="module")
def par_llaves():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _token(priv, **over):
    # Use current time to ensure tokens don't expire
    ahora = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": "user-123", "email": "x@obra.co", "aud": "authenticated",
        "iss": ISS, "iat": ahora, "exp": ahora + dt.timedelta(hours=1)}
    payload.update(over)
    return jwt.encode(payload, priv, algorithm="RS256")


def test_token_valido_devuelve_claims(par_llaves):
    priv, pub = par_llaves
    claims = verificar_token(_token(priv), pub, issuer=ISS)
    assert claims["sub"] == "user-123" and claims["email"] == "x@obra.co"


def test_token_expirado_falla(par_llaves):
    priv, pub = par_llaves
    viejo = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    t = _token(priv, iat=viejo, exp=viejo + dt.timedelta(hours=1))
    with pytest.raises(ErrorAuth):
        verificar_token(t, pub, issuer=ISS)


def test_aud_incorrecto_falla(par_llaves):
    priv, pub = par_llaves
    with pytest.raises(ErrorAuth):
        verificar_token(_token(priv, aud="otra"), pub, issuer=ISS)


def test_iss_incorrecto_falla(par_llaves):
    priv, pub = par_llaves
    with pytest.raises(ErrorAuth):
        verificar_token(_token(priv, iss="https://malo/auth/v1"), pub, issuer=ISS)


def test_firma_de_otra_llave_falla(par_llaves):
    priv, pub = par_llaves
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ErrorAuth):
        verificar_token(_token(otra), pub, issuer=ISS)
