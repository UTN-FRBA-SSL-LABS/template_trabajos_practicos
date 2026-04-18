int process(int data);

int compute(int val) {
    int result = process(val);
    return result;
}

int main(void) {
    int x = compute(10);
    int y = unknown(x);
    return x;
}
