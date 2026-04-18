void countdown(int n);

int classify(int x) {
    switch (x) {
        case 1:
            return 10;
        case 2:
            return 20;
        default:
            return 0;
    }
}

void countdown(int n) {
    do {
        n--;
    } while (n > 0);
}
