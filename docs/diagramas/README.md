# Diagramas UML

Fuentes en PlantUML (`.puml`) y su imagen generada (`.png`). Todos comparten el estilo de `estilo.iuml`.

| Diagrama | Fuente | Imagen |
|---|---|---|
| Casos de uso | `01_casos_de_uso.puml` | `casos_de_uso.png` |
| Clases: modelo de dominio | `02_clases.puml` | `clases.png` |
| Clases: servicios y patrones | `02b_clases_patrones.puml` | `clases_patrones.png` |
| Secuencia: solicitud urgente | `03_secuencia.puml` | `secuencia.png` |
| Despliegue en la nube | `04_despliegue.puml` | `despliegue.png` |

Para regenerar las imágenes (requiere Java y Graphviz):

```bash
java -jar plantuml.jar -tpng *.puml
```

También se pueden pegar en https://www.planttext.com junto con el contenido de `estilo.iuml`.
