# J.A.R.V.I.S para Windows

Asistente de escritorio en español, mantenido por **Sukima Labs**. Usa Gemini como backend y una interfaz HUD para voz, conversación, métricas del sistema y vigilancia visual rotativa.

## Inicio rápido

1. Instala Python 3.10 o posterior.
2. Instala las dependencias: `pip install -r requirements.txt`.
3. Copia `config/api_keys.example.json` como `config/api_keys.json` y añade tu clave de Gemini.
4. Ejecuta `start.bat`.

`config/api_keys.json`, la memoria local, el entorno virtual y las grabaciones privadas adicionales se excluyen de Git. No subas claves ni archivos de memoria.

## Medios de la interfaz

El repositorio incluye las animaciones de Iron Man bajo Lottie Simple License y sus creditos en `assets/ATTRIBUTIONS.md`. Los GIF de peliculas se conservan localmente. El audio de inicio aportado por el usuario esta en `assets/back_in_black_intro.mpeg` para este repositorio privado.

## Interfaces

En **Configuración → Interfaz** puedes elegir entre **Mando Sukima**, **Visor azul** y **Mapa táctico**. `F6` cambia al siguiente diseño. La selección se conserva al reiniciar. Los fondos del visor y del mapa táctico son imágenes originales creadas para este proyecto; cada modo tiene una animación central diferente y conserva la conversación, el estado de Gemini y la vigilancia visual.

## Marca

El isotipo maestro es `isotipo_color.svg`; los iconos de Windows están en `assets/`.
