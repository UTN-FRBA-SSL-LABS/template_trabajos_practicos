int main(void) {
    char *msg = "ok";
    int i = 0;
    int j = 10;
    do {
        i++;
        j--;
        if (i == j || i >= 8) {
            j += 2;
        } else {
            i -= 1;
        }
    } while (i != j && i <= 10);
    @err@
    return 0;
}
