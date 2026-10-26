# Co da się przenieść

Lista decyzji. Użytkownik wybiera jedną opcję. Resztę prowadzi konwerter.
Rekordbox idzie metodą z `VDJ_RB_MIGRACJA.md` (wklej XML, przeciągnij folder Serato).

## Da się od razu

- **VirtualDJ → Engine.** Utwory, listy, BPM, tonacja, hot cue i beatgrid. Listy-filtry VDJ stają się zwykłymi listami z utworami, które wtedy na nich były.
- **VirtualDJ → Rekordbox.** Utwory, artysta, listy, cue i beatgrid w XML. Dalej kroki z metody Rekordbox.
- **Serato → Rekordbox.** Utwory, artysta, BPM, tonacja, ocena i drzewo crate'ów. Potem metoda Rekordbox. Listy lądują w folderze Serato.
- **Serato → Engine.** Utwory, artysta i drzewo crate'ów.
- **Engine → Rekordbox.** Utwory i playlisty, tym samym XML co wyżej.
- **Engine → VirtualDJ.** Utwory i playlisty do `database.xml` i plików `.vdjfolder`.

## Da się, ale trzeba wybrać

- **Hot cue i beatgrid z Serato.** Nie ma ich w `master.sqlite`. Serato trzyma je w tagu Markers2 w pliku audio. Opcja: „Czytaj cue z plików” (wolniejsze, plik musi leżeć na dysku) albo „Pomiń cue”.
- **Hot cue z Engine.** Odczyt `m.db` bierze utwory i playlisty. Cue i beatgrid wchodzą do Engine, gdy źródłem jest VirtualDJ. Z Engine na inny program cue na razie nie wychodzą. Opcja: „Przenieś listy i tagi” (to działa) albo „Zostaw cue w Engine”.
- **Zapis do Serato.** Konwerter pisze `database V2` i pliki `.crate` w `~/Music/_Serato_`. Nie zapisuje `master.sqlite`, `root.sqlite` ani `tidal.sqlite`, bo bezpośredni zapis tych trzech baz psuje bibliotekę. Opcja: „Zapisz crate'y, Serato sam je wczyta po restarcie”.
- **Utwór już jest w Rekordboxie.** Program nie podmienia tagów. Opcja: „Wgraj od nowa” (usuń utwory z kolekcji, pliki zostają) albo „Dopisz tylko nowe listy”.
- **Tidal, netsearch, .vdjcache.** Zostaje ścieżka albo numer streamu. Drugi program nie zagra tego jako pliku, dopóki nie ma lokalnej kopii. Opcja: „Zostaw streaming” albo „Pomiń utwory bez pliku”.
- **Brakujący plik.** Rekordbox pomija go i dopisuje do `~/Documents/rekordbox/Import Log`. Reszta importu dochodzi.

## Nie da się tym konwerterem

- Smart crate Serato i reguły filtrów VirtualDJ jako żywe reguły. Wychodzi zwykła lista albo pusta nazwa.
- Stemy Engine jako część XML. To osobne pliki, nie biblioteka.
- Zapis kolekcji wprost do `master.db` Rekordboxa.
- Cue Serato w XML, jeśli nie wybrano czytania tagów z plików.
