# Licencja przed publikacją

Przypomnienie na dzień wydania. Nie publikować buildu, dopóki ten model nie jest podłączony.

Obecny kod (`license_njr.py`) puszcza eksport bez konta. To jest stan tymczasowy, nie model wydania.

## Docelowy model

- Rejestracja jest darmowa i obowiązkowa. Bez konta program nie pracuje na bazie.
- W programie jest zakładka **Moje konto**: zalogowany użytkownik i stan tokenów.
- Tokeny kupuje się na koncie. Pakiety ilościowe (ile tokenów, jaka cena, co jeden token zużywa) ustalamy osobno, przed publikacją.
- Płatność idzie przez istniejący sklep Stripe, nie przez klucz licencji wklejany w program.

## Czego nie robić przy wydaniu

- Nie zostawiać trybu „open source, eksport bez klucza” jako zachowania publicznego buildu.
- Nie ustalać cen pakietów w kodzie, dopóki nie są podane.
