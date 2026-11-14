# Naming Conventions

This glossary is a naming guide for contributors. Parts of the original code and working notes use Portuguese identifiers. Use the English terms below in new code, comments and documentation. Camera protocol names (`pro`, `cmd`, `user`, `pwd`, `lamp`, `icut`, `sysver`, `wifissid`, ...) are the camera's wire names and are never translated.

## Core terms

| Portuguese | English | Where it is used |
|---|---|---|
| quadro | frame | `code/video_assemble.py` (`frames`, `_complete`), `code/cy_viewer.py` (`_latest`), `code/teste_audio.py` (`FrameParser.frames`), `app/servidor.py` (`_frame_count`) |
| pacote | packet | `code/cy_session.py` (`_command_packet`, `_recv`), `code/teste_audio.py` (`packets`), `code/probe_leitura.py` (`packets` in notes) |
| payload | payload | unchanged (already English) |
| sessão | session | `code/cy_session.py` (`CameraSession`, `_session`), `app/servidor.py` (`_active_session`, `State.session`) |
| estado (sessão) | state | `app/servidor.py` (`State`, `state`, `start_connection`), page `appState` |
| estado (JSON value) | state | `/api/estado` reply key `state`; values `disconnected`, `connecting`, `connected`, `error` |
| resposta | response | `code/cy_session.py` (`_json_from_response`, `_response_packet`), `code/probe_leitura.py` (`response`) |
| erro | error | `app/servidor.py` (`_error`, API key `error`), page `d.error` |
| etapa | stage | `code/cy_session.py` (`CameraError.stage`), `app/servidor.py` (API key `stage`) |
| motivo | reason | `code/cy_session.py` (`CameraError.reason`), `app/servidor.py` (`State.update(reason=...)`) |
| detalhe | detail | `app/servidor.py` (API key `detail`) |
| login | login | unchanged (same word); `code/cy_session.py` (`login`), `code/probe_leitura.py` (`login`) |
| comando | command | `code/cy_session.py` (`command`, `_send_command_no_reply`), `app/servidor.py` (`_command`) |
| canal | channel | `code/cy_session.py` (`CHANNEL_CMD`, `CHANNEL_VIDEO`), `code/video_assemble.py` (`CHANNEL`) |
| fluxo | stream | `code/cy_client.py`, `code/cy_session.py` (`start_video`, `start_audio`), `/stream`, `/audio.wav` |
| amostra | sample | `code/teste_audio.py` (`samples_of`, `metrics`) |
| pico | peak | `code/teste_audio.py` (`peak` in tests); printed metric label `pico` kept (see below) |
| tamanho | size | `code/teste_audio.py` (`MAX_FRAME_SIZE`, `n_size_mismatch`) |
| cabeçalho | header | `code/teste_audio.py` (`AV_HEADER_LEN`, `header`), `app/servidor.py` (`header`) |
| corpo | body | `app/servidor.py` (`_body`), `code/probe_leitura.py` (`build_body`) |
| campos | fields | `app/servidor.py` (`_fields`, API key `fields`), `code/probe_leitura.py` (`fields`) |
| confirmado | confirmed | `app/servidor.py` (API key `confirmed`, `write` routes) |
| escrita | write | `app/servidor.py` (`write` flag in resource list, API key `write`) |
| recursos | resources | `app/servidor.py` (`load_resources`, API key `resources`) |
| prioridade | priority | `app/servidor.py` (API key `priority`) |
| provado | proven | `app/servidor.py` (API key `proven`) |
| nome | name | `app/servidor.py` (API key `name`) |
| sucesso | success | `app/servidor.py` (API key `success`) |
| fábrica | factory | `app/servidor.py` (`App.factory`, `create_server(factory=...)`) |
| dublê / falsa | fake | `app/servidor.py` (`FakeCamera`), `code/cy_session.py` (`_FakeSocket`), `app/teste_servidor_falso.py` |
| sonda | probe | `code/probe_leitura.py` (`probe`) |
| plano | plan | `code/probe_leitura.py` (`plan`) |
| escolher | choose | `code/probe_leitura.py` (`choose`) |
| validar | validate | `code/probe_leitura.py` (`validate_command`) |
| gravar | save | `code/probe_leitura.py` (`save_capture`), `code/teste_audio.py` (`save_wav`) |
| capturar | capture | `code/teste_audio.py` (`capture`, `run_capture`) |
| executar | run | `code/teste_audio.py` (`run_capture`) |
| medir | measure | `code/teste_visao_noturna.py` (`measure`, `measure_phase`) |
| métricas | metrics | `code/teste_audio.py` (`metrics`) |
| montar | build / assemble | `code/teste_audio.py` (`build_frames`), `code/probe_leitura.py` (`build_body`) |
| ler | read | `code/video_assemble.py` (`read_dump`), `code/teste_audio.py` (`read_wav`) |
| publicar | publish | `code/cy_viewer.py` (`publish`), `app/servidor.py` (`publish`) |
| iniciar | start | `app/servidor.py` (`start`, `start_connection`) |
| mudar | update | `app/servidor.py` (`State.update`) |
| ouvir | listen | `app/servidor.py` (`State.listen`, `stop_listening`) |
| definir | set | `app/servidor.py` (`State.set_session`) |
| pendente | pending | `code/teste_audio.py` (`FrameParser.pending`) |
| descartado | discarded | `code/video_assemble.py` (`n_discarded`), `code/teste_audio.py` (`n_*`) |
| completo | complete | `code/video_assemble.py` (`n_complete`, `complete`) |
| ligado | started | `code/teste_audio.py` (`started`) |
| senha | password | `code/cy_session.py` (`password` in docs), `app/servidor.py` (`password` variables) |
| pausa | pause | `code/probe_leitura.py` (`PAUSE_S`, `--pausa`) |
| janela | window | `code/video_assemble.py` (`window`), `code/cy_session.py` (`VIDEO_WINDOW`) |
| prazo | deadline | `code/cy_session.py`, `app/servidor.py` |
| espera | wait | `code/cy_session.py` (`wait`, `wait_s`) |
| intervalo | interval | `code/cy_viewer.py` (`interval`) |
| pasta | folder | `code/probe_leitura.py`, `code/cy_viewer.py` (`--demo` folder), `code/teste_audio.py` |
| caminho | path | `code/probe_leitura.py`, `code/teste_audio.py` (`path`) |
| saída | output | `code/probe_leitura.py` (`output`), `code/teste_audio.py` (`output`) |
| teste | test | `tests` (functions `_tests`), test names in English |
| falha | failure | `code/cy_session.py`, `app/servidor.py` (`command_failure`, `login_failure`), `failures` |

## Intentionally kept in Portuguese

| What | Where | Why |
|---|---|---|
| CLI flags: `--pwd`, `--cam`, `--segundos`, `--confirmar`, `--plano`, `--testes`, `--embaralhar`, `--exemplos`, `--espera`, `--pausa`, `--so`, `--pcap`, `--out` | all scripts | Users type them, and documentation quotes them. Each flag gets an English `dest` (e.g. `--segundos` -> `args.seconds`). |
| API URL paths: `/api/conectar`, `/api/desconectar`, `/api/comando` | `app/servidor.py`, page | Public URL contract (ui_spec, design). Not an identifier. |
| API error and status messages: `"Senha obrigatoria"`, `"Sessao ja conectada"`, `"Senha incorreta"`, `"Camera nao respondeu..."` | `app/servidor.py` | Shown to the user in the page. |
| Terminal messages (`print`, log lines) | all scripts | Translated to English; result labels are `RESULT` and `FAILED`. |
| Probe output file keys: `comandos`, `resposta`, `erro`, `tempo_s`, `enviado_em`, `campos`, `status`, `gerado_em` | `code/probe_leitura.py` -> `captures/probe/*.json` | Existing capture files and the camera capabilities document (`docs/camera-capabilities.md`) depend on them. |
| Probe status values `"ok"`, `"sem resposta"` | `code/probe_leitura.py` | Written into the capture JSON; kept for compatibility with earlier captures. |
| Metric labels printed by `code/teste_audio.py --pcap` (`amostras`, `duracao_s`, `rms`, `pico`, `pct_nao_zero`, `pct_acima_piso`) | `code/teste_audio.py` | Printed labels quoted in test reports. |
| File names: `teste_*.py`, `servidor.py`, `capacidades_*.json`, `features.md` | repo | Referenced by existing scripts and reports, so they are kept stable. |
| Data and protocol names: `pro`, `cmd`, `user`, `pwd`, `lamp`, `icut`, `sysver`, `wifissid`, `encwifipwd`, `enc`, `power`, `charging`, `time`, `ssid`, `conmode`, `devmac`, `checkstr` | everywhere | Camera wire protocol. |
| Codec/hardware names: `ADPCMDecode`, `ADecode`, `AEncode`, `PunchPkt`, `LanSearch`, `DevLgn` | docs and tests | Names from the app/SDK. |
