int square(int n) {
    return n * n;
}

int main(void) {
    const int limit = 10;
    int result = square(limit, 2);
    result = square();
    limit = 20;
    return result;
}
