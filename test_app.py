from flask import Flask, request, render_template

app = Flask(__name__)

request_log = []

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        headers = dict(request.headers)
        body = request.get_data(as_text=True)
        request_log.append({'headers': headers, 'body': body})

    return render_template('test.html', request_log=request_log)


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=60054)
