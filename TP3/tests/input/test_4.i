int add(int a, int b) {
    return a + b;
}

int main(void) {
    int i, total = 0;
    int limit = 10;
    for (i = 0; i < limit; i += 1) {
        if (i > 5) {
            total += i;
        }
    }
    return total;
}
