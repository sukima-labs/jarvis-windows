"""Sucesos ficticios para la simulación de vigilancia del UCM.

Contexto narrativo: https://www.marvel.com/movies/doctor-strange-in-the-multiverse-of-madness
y https://www.marvel.com/characters/loki/ . Ninguna entrada es una noticia en vivo.
"""

EVENTS = (
    ("FRACTURA TEMPORAL", "La línea del tiempo se ha ramificado. La TVA investiga la divergencia.", "Loki"),
    ("PORTAL MULTIVERSAL", "Doctor Strange ha cruzado a otra realidad. Wong sigue el rastro del portal.", "Doctor Strange"),
    ("SEÑAL DE WAKANDA", "Shuri ha detectado una anomalía de vibranio cerca de Wakanda.", "Black Panther"),
    ("ACTIVIDAD CÓSMICA", "Capitana Marvel ha registrado una descarga de energía en el espacio profundo.", "Capitana Marvel"),
    ("REINO CUÁNTICO", "Ant-Man informa de fluctuaciones en el Reino Cuántico.", "Ant-Man"),
    ("VIGILANCIA EN QUEENS", "Spider-Man sigue una señal desconocida sobre Queens.", "Spider-Man"),
    ("TRANSMISIÓN GUARDIANES", "Los Guardianes de la Galaxia han enviado una señal desde el sector exterior.", "Guardianes"),
    ("ENERGÍA ASGARDIANA", "Thor ha activado una tormenta eléctrica de intensidad inusual.", "Thor"),
    ("ALERTA AVENGERS", "Capitán América solicita reunir al equipo para revisar una nueva amenaza.", "Avengers"),
    ("BRUJA ESCARLATA", "Una firma de magia del caos aparece en el mapa multiversal.", "Wanda"),
    ("PUNTO DE INCURSIÓN", "El mapa multiversal muestra dos realidades en contacto. El análisis continúa.", "Multiverso"),
    ("PROTOCOLO DE DEFENSA", "Wakanda ha reforzado la vigilancia alrededor de su tecnología de vibranio.", "Wakanda"),
)


def build_event_prompt(event: tuple[str, str, str]) -> str:
    """Describe an alert to JARVIS and keep its details available for follow-up."""
    title, description, related_work = event
    return (
        "Acaba de ocurrir un evento dentro del universo del UCM.\n"
        f"Evento: {title}.\n"
        f"Descripción: {description}\n"
        f"Contexto relacionado: {related_work}.\n\n"
        "Anúncialo con una sola frase breve que empiece exactamente por: "
        "«Acaba de ocurrir un evento dentro del universo del UCM». "
        "Explica el evento usando el título, la descripción y el contexto relacionado. "
        "Conserva estos datos para las preguntas siguientes y explica a qué evento "
        "se refieren aunque el usuario diga solamente «el evento». No digas que no "
        "sabes qué evento es. Este aviso es una historia original ambientada en el "
        "universo del UCM, no una noticia ni un hecho canónico; no lo anuncies como "
        "una simulación ni inventes detalles de las películas."
    )
