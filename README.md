# T-Rex PS1 — rig Blender editável (primeira passada)

Fonte: *PlayStation — Developer's Demo CD — Models — Dino*. A pasta `source/dino` contém o OBJ, o MTL e as seis texturas PNG originais.

## No Mac, inteiramente pelo terminal

Instale o Blender, se ainda não estiver instalado:

```bash
brew install --cask blender
```

Entre na pasta descompactada e execute:

```bash
chmod +x run_mac.sh
./run_mac.sh
```

O script **gera localmente**, se executado corretamente com Blender:

- `output/trex_editable.blend`: projeto com geometria, UVs, materiais, armature e vertex groups editáveis.
- `output/trex_blender_rig.glb`: exportação GLB via exporter do Blender (sem clipes de animação).

Abra a cena gerada:

```bash
open output/trex_editable.blend
```

Para executar manualmente com caminhos diferentes:

```bash
"/Applications/Blender.app/Contents/MacOS/Blender" \
  --background --factory-startup --python rig_trex_blender.py -- \
  --source ./source/dino/dino.obj --out-dir ./output --export-glb
```

## Como corrigir os pivôs no Blender

1. Selecione `TREX_EDITABLE_ARMATURE` no Outliner. Para vista lateral, use **View → Viewpoint → Right** (ou **Numpad 3**). Use **Numpad 5** para alternar para vista ortográfica.
2. Entre em **Edit Mode** (`Tab`), selecione os ossos `Thigh.L`, `Shin.L`, `Tarsus.L` e `Foot.L`. Mova as cabeças e pontas com `G`, conforme a malha real. Faça o mesmo com `.R`. Os ossos têm hierarquia, mas não são `Connected`, então cada junta pode ser ajustada.
3. Em **Pose Mode** (`Ctrl+Tab`, conforme keymap), teste **apenas um osso por vez**. Comece por `Shin.L`, não por todo o rig.
4. Para refinar as deformações, selecione a malha `PS1_TREX_Original_Geometry`, mude para **Weight Paint** e escolha os grupos `Thigh.L`, `Shin.L`, `Tarsus.L`, `Foot.L`, `Toes.L` em Object Data → Vertex Groups.
5. A malha possui triângulos e UVs originais, sem retopologia. Bordas de materiais e polígonos duplicados podem precisar de ajuste conjunto para evitar frestas.

Os pontos de referência iniciais ficam em `JOINTS` no arquivo `rig_trex_blender.py`, em **unidades do OBJ**. O screenshot anotado `diagnostics/leg_joint_overlay.png` mostra a aproximação usada.

## O que isto corrige e o que não corrige

- Reconstrói o esqueleto **no Blender**, com armature modificável e `Vertex Groups` reais. Não utiliza as matrizes inversas de bind escritas manualmente nas versões GLB anteriores.
- Usa joelho projetado para frente, hock mais atrás, tornozelo baixo e dedos na frente, alinhando a cadeia à silhueta lateral em vez de posicioná-la quase reta.
- Os pesos iniciais são normalizados e limitados a quatro ossos por vértice, com mistura concentrada nas articulações.
- **Não** é skinning manual finalizado; o script não substitui inspeção em Pose Mode e ajustes em Weight Paint.
- A mandíbula **não recebe pesos automáticos** porque o OBJ não comprova uma mandíbula topologicamente separada. O osso `Jaw` é criado para futura separação/pintura manual.
- Nenhuma caminhada foi inventada. Primeiro valide as articulações, depois faça as animações.

## Validação sem Blender

```bash
python3 test_rig_math.py
```

Esse teste verifica OBJ, contagem de vértices e triângulos, normalização e presença de pesos nas duas pernas. **Não** comprova a qualidade visual de deformação em tempo real.
