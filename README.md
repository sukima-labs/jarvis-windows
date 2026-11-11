# J.A.R.V.I.S para Windows

Asistente de escritorio en español, mantenido por **Sukima Labs**. Usa Gemini como backend y una interfaz HUD para voz, conversación, métricas del sistema y vigilancia visual rotativa.

## Inicio rápido

1. Instala Python 3.10 o posterior.
2. Instala las dependencias: `pip install -r requirements.txt`.
3. Copia `config/api_keys.example.json` como `config/api_keys.json` y añade tu clave de Gemini.
4. Ejecuta `start.bat`.

`config/api_keys.json`, la memoria local, el entorno virtual y las grabaciones privadas adicionales se excluyen de Git. No subas claves ni archivos de memoria.

## Medios de la interfaz

El repositorio incluye las animaciones de Iron Man bajo Lottie Simple License, las secuencias GIF y sus fuentes en `assets/ATTRIBUTIONS.md` y `assets/vigilancia_sources.json`. El audio de inicio aportado por el usuario esta en `assets/back_in_black_intro.mpeg` para este repositorio privado. La carpeta `posibles interfaz` contiene las referencias visuales aportadas por el usuario.

## Interfaces

En **Configuración → Interfaz** puedes elegir entre **Mando Sukima**, **Visor azul**, **Mapa táctico**, **Armadura / HUD**, **Archivo neural** y **Centro orbital**. `F6` cambia al siguiente diseño. La selección se conserva al reiniciar. Los fondos del visor y del mapa táctico son imágenes originales creadas para este proyecto. En pantallas anchas, Visor usa una consola panorámica con instrumentos satélite; Armadura integra diagnósticos alrededor de una figura original; y Archivo neural muestra una red horizontal animada de circuitos. Estas tres vistas enseñan varios GIF de vigilancia simultáneamente y mantienen el chat en un panel contextual. En pantallas estrechas vuelven a la distribución compacta. Cada modo conserva la conversación, el estado de Gemini y la vigilancia visual.

El botón **INTERFAZ** de la cabecera también cambia el diseño con un clic. El repositorio contiene 92 secuencias de películas y series del UCM; sus fuentes de GIPHY y Tenor figuran en `assets/vigilancia_sources.json`. Si falta alguna, `venv\Scripts\python.exe scripts\install_vigilancia.py` la recupera. El botón **SIGUIENTE** pasa a otra secuencia.

La vigilancia reproduce GIF animados de forma continua y, cada cierto tiempo, muestra un aviso ficticio del UCM en pantalla. Si Jarvis está conectado y lleva un rato sin conversación, también lo comenta en voz. Estos avisos son una simulación narrativa basada en personajes y mundos de las películas, no noticias ni detecciones reales. El panel **Centro de avisos** muestra el último suceso y la cuenta regresiva del siguiente; la telemetría del equipo permanece en su panel independiente.

El botón **Silenciar micrófono** (o `F4`) deja Jarvis en marcha y mantiene sus respuestas de voz. Durante cada respuesta, Jarvis corta temporalmente la entrada del micrófono, descarta audio pendiente y espera un instante al terminar para que Gemini no interprete su propia voz como una orden del usuario. Los avisos del UCM comienzan con un sonido breve original y siguen con el comentario hablado.

## Marca

El isotipo maestro es `isotipo_color.svg`; los iconos de Windows están en `assets/`.
