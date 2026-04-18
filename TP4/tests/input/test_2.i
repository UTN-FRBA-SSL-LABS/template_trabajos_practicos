int add(int a, int b) {
    return a + b;
}

int multiply(int x, int y) {
    return x * y;
}

int main(void) {
    int n = 5;
    int m = 3;
    int sum = add(n, m);
    int product = multiply(n, m);
    return sum + product;
}
