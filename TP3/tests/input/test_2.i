int factorial(int n) {
    int result = 1;
    while (n > 0) {
        result *= n;
        n -= 1;
    }
    return result;
}

int main(void) {
    int x = 5;
    int y = factorial(x);
    if (y > 100) {
        return 1;
    } else {
        return 0;
    }
}
